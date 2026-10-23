"""app.media.scraper — 媒体元数据刮削模块

重构后架构:
  - Scraper           — 主协调类（保持原有 API）
  - NfoGenerator      — NFO XML 生成
  - ImageDownloader   — 图片下载与文件保存
  - MediaLibrary      — 媒体库文件遍历与 NFO 读取
  - ChineseCredits    — 豆瓣演职人员中文名匹配
"""

import json
import os
import re
import time

from PIL import Image

import log
from app.core.module_config import ModuleConf
from app.core.settings import settings
from app.core.system_config import SystemConfig
from app.db.repositories.download_repo_adapter import DownloadHistoryRepositoryAdapter
from app.domain.enums import SystemConfigKey
from app.domain.mediatypes import MediaType
from app.infrastructure.ffmpeg import FfmpegProcessor
from app.infrastructure.image_proxy import ImageProxy
from app.infrastructure.temp import temp_manager
from app.media.external.douban import DouBan
from app.media.fanart import Fanart
from app.media.metadata.images import ImageResolver
from app.media.metadata.models import Credit, ImageAsset
from app.media.metadata.parsing import ParserChain
from app.media.parser._metainfo import meta_info
from app.media.service import MediaService
from app.utils import ExceptionUtils
from app.utils.json_utils import JsonUtils

from .chinese_credits import ChineseCredits
from .image_downloader import ImageDownloader
from .media_library import MediaLibrary
from .nfo_generator import NfoGenerator
from .processor_registry import scraper_processor_registry

_PART_SUFFIX_RE = re.compile(r"(?i)[-_. ]?(?:cd|part|pt|disk|disc|dvd)\s*[1-9a-d]$")


def _nfo_base_name(file_path: str) -> str:
    """去掉 cd1/part1 等分段后缀，Emby 会把这些文件堆叠为一个影片."""
    stem = os.path.splitext(os.path.basename(file_path))[0]
    return _PART_SUFFIX_RE.sub("", stem)


class Scraper:
    """媒体元数据刮削器 — 生成 NFO 文件、下载图片"""

    def __init__(
        self,
        media_service: MediaService,
        douban: DouBan | None = None,
        system_config: SystemConfig | None = None,
        metadata_service=None,
    ):
        self.media = media_service
        self._metadata_service = metadata_service
        self.douban = douban or DouBan()
        self.fanart = Fanart()
        self._system_config = system_config or SystemConfig()
        self._scraper_flag = False
        self._scraper_nfo = {}
        self._scraper_pic = {}
        self._rmt_mode = None
        self._temp_path = temp_manager.create_subdir("scraper")
        self._init_config()
        self._downloader = ImageDownloader(self._temp_path)
        self._nfo_gen = NfoGenerator(self._downloader)
        self._images = ImageResolver()
        self._credits = ChineseCredits(self.media)

    def _init_config(self):
        self._scraper_flag = (settings.get("media") or {}).get("nfo_poster")
        self._legacy_tmdb_fallback = bool((settings.get("media") or {}).get("legacy_tmdb_fallback", True))
        scraper_conf = self._system_config.get(SystemConfigKey.UserScraperConf)
        if isinstance(scraper_conf, str):
            try:
                scraper_conf = JsonUtils.loads(scraper_conf)
                # 兼容旧版双重 JSON 编码（set_scraper_config 曾用 json.dumps 预编码）
                if isinstance(scraper_conf, str):
                    scraper_conf = JsonUtils.loads(scraper_conf)
            except Exception:
                scraper_conf = None
        if isinstance(scraper_conf, dict):
            self._scraper_nfo = scraper_conf.get("scraper_nfo") or {}
            self._scraper_pic = scraper_conf.get("scraper_pic") or {}

    @staticmethod
    def _profile_media_info(file_path: str):
        """用插件注册的 ParserProfile 从文件名构造媒体信息."""
        parsed = ParserChain().extract(os.path.basename(file_path))
        if parsed is None or not getattr(parsed, "content_profile", None):
            return None
        code = getattr(parsed, "anchor_external_id", None) or os.path.basename(file_path)
        media_info = meta_info(code, mtype=getattr(parsed, "type", None) or MediaType.MOVIE)
        media_info.content_profile = parsed.content_profile
        media_info.anchor_provider = getattr(parsed, "anchor_provider", "") or ""
        media_info.anchor_external_id = getattr(parsed, "anchor_external_id", "") or ""
        return media_info

    def folder_scraper(self, path, exclude_path=None, mode=None, dst_backend=None):
        """刮削指定文件夹或文件"""
        try:
            force_nfo = mode in ["force_nfo", "force_all"]
            force_pic = mode == "force_all"
            self._downloader.set_dst_backend(dst_backend)
            files = list(MediaLibrary.get_library_files(path, exclude_path, backend=dst_backend))
            log.info(f"[Scraper]发现 {len(files)} 个待刮削文件")
            for file in files:
                if not file:
                    continue
                log.info(f"[Scraper]开始刮削媒体库文件：{file} ...")
                mi = meta_info(os.path.basename(file))
                profile_info = self._profile_media_info(file)
                if profile_info is not None and self._metadata_service is not None:
                    snapshot = self._metadata_service.compose_for_media(profile_info, with_episodes=True, persist=True)
                    if snapshot is not None:
                        self.gen_snapshot_files(
                            snapshot=snapshot,
                            media=profile_info,
                            dir_path=os.path.dirname(file),
                            file_name=_nfo_base_name(file),
                            file_ext=os.path.splitext(file)[-1],
                            force_nfo=force_nfo,
                            force_pic=force_pic,
                            dst_backend=dst_backend,
                        )
                        log.info(f"[Scraper]{file} 插件画像快照刮削完成")
                        continue
                    log.warn(f"[Scraper]{file} 插件画像无法合成元数据快照")
                tmdbid = self._extract_tmdbid(file, mi, dst_backend)
                if tmdbid and not force_nfo:
                    log.info(f"[Scraper]读取到本地nfo文件的tmdbid：{tmdbid}")
                    mi.set_provider_data(
                        self.media.get_tmdb_info(mtype=mi.type, tmdbid=tmdbid, append_to_response="all")
                    )
                    media_info = mi
                else:
                    # 尝试从下载历史中读取订阅时记录的 TMDB 信息（TMDB 身份确定，季/集仍从文件名解析）
                    (
                        dl_tmdbid,
                        dl_type,
                        dl_anchor_provider,
                        dl_anchor_external,
                        dl_content_profile,
                    ) = self._download_history_tmdb(file)
                    if dl_tmdbid or dl_anchor_provider:
                        log.info(f"[Scraper]从下载历史读取到tmdbid：{dl_tmdbid}，类型={dl_type}")
                        dl_mtype = MediaType.from_string(dl_type) or mi.type or MediaType.MOVIE
                        db_anchor = str(dl_tmdbid or "").startswith("DB:") or (
                            dl_anchor_provider and dl_anchor_provider != "tmdb" and not str(dl_tmdbid or "").isdigit()
                        )
                        if db_anchor:
                            # 豆瓣直连：不查询 TMDB，季/集只从文件名解析
                            media_info = mi
                            media_info.tmdb_id = str(dl_tmdbid) if str(dl_tmdbid or "").startswith("DB:") else ""
                            media_info.douban_id = str(dl_anchor_external or "").strip() or (
                                str(dl_tmdbid)[3:] if str(dl_tmdbid or "").startswith("DB:") else ""
                            )
                            media_info.type = dl_mtype
                            log.info(f"[Scraper]豆瓣订阅刮削使用豆瓣元数据：{dl_anchor_external}")
                        else:
                            tmdb_details = self.media.get_tmdb_info(
                                mtype=dl_mtype, tmdbid=dl_tmdbid, append_to_response="all"
                            )
                            if tmdb_details:
                                mi.set_provider_data(tmdb_details)
                                # 再用 identify_files 解析季/集（有 tmdb_info 时跳过网络查询，仅做本地解析）
                                medias = self.media.get_media_info_on_files(
                                    file_list=[file],
                                    tmdb_info=tmdb_details,
                                    media_type=dl_mtype,
                                    append_to_response="all",
                                    backend=dst_backend,
                                )
                                if medias:
                                    media_info = next(iter(medias.values()), mi)
                                else:
                                    media_info = mi
                            else:
                                media_info = mi
                        media_info.anchor_provider = dl_anchor_provider or media_info.anchor_provider
                        media_info.anchor_external_id = dl_anchor_external or media_info.anchor_external_id
                        media_info.content_profile = dl_content_profile or media_info.content_profile or "default"
                    else:
                        medias = self.media.get_media_info_on_files(
                            file_list=[file], append_to_response="all", backend=dst_backend
                        )
                        if not medias:
                            log.warn(f"[Scraper]{file} 无法识别媒体信息")
                            continue
                        media_info = next(iter(medias.values()), None)
                metadata_service = self._metadata_service
                if media_info is not None and metadata_service is not None:
                    snapshot = metadata_service.compose_for_media(media_info, with_episodes=True, persist=True)
                    if snapshot is not None:
                        self.gen_snapshot_files(
                            snapshot=snapshot,
                            media=media_info,
                            dir_path=os.path.dirname(file),
                            file_name=os.path.splitext(os.path.basename(file))[0],
                            file_ext=os.path.splitext(file)[-1],
                            force_nfo=force_nfo,
                            force_pic=force_pic,
                            dst_backend=dst_backend,
                        )
                        log.info(f"[Scraper]{file} 快照刮削完成")
                        continue
                    log.warn(f"[Scraper]{file} 无法合成元数据快照")
                if not self._legacy_tmdb_fallback:
                    log.warn(f"[Scraper]{file} legacy TMDB 回退已禁用，跳过")
                    continue
                if not media_info or not media_info.provider_data:
                    log.warn(f"[Scraper]{file} 无法获取TMDB信息")
                    continue
                self.gen_scraper_files(
                    media=media_info,
                    dir_path=os.path.dirname(file),
                    file_name=os.path.splitext(os.path.basename(file))[0],
                    file_ext=os.path.splitext(file)[-1],
                    force=True,
                    force_nfo=force_nfo,
                    force_pic=force_pic,
                    dst_backend=dst_backend,
                )
                log.info(f"[Scraper]{file} 刮削完成")
        except Exception as e:
            log.error(f"[Scraper]刮削异常：{e}")
            ExceptionUtils.exception_traceback(e)

    def gen_snapshot_files(
        self, snapshot, media, dir_path, file_name, file_ext, force_nfo=False, force_pic=False, dst_backend=None
    ):
        """无 TMDB 场景：直接消费 MediaMetadata 快照生成 NFO/图片."""
        self._init_config()
        if not self._scraper_nfo and not self._scraper_pic:
            log.warn("[Scraper]刮削配置为空，跳过快照刮削")
            return
        self._dst_backend = dst_backend
        self._downloader.set_dst_backend(dst_backend)
        if not getattr(snapshot, "content_profile", "") and getattr(media, "content_profile", ""):
            snapshot.content_profile = media.content_profile
        if media.type == MediaType.MOVIE:
            self._scrape_movie_from_snapshot(snapshot, dir_path, file_name, force_nfo, force_pic)
        else:
            self._scrape_tv_from_snapshot(snapshot, media, dir_path, file_name, file_ext, force_nfo, force_pic)

    def _scrape_movie_from_snapshot(self, snapshot, dir_path, file_name, force_nfo, force_pic):
        scraper_movie_nfo = self._scraper_nfo.get("movie", {})
        scraper_movie_pic = self._scraper_pic.get("movie", {})
        self._ensure_snapshot_images(snapshot)
        scraper_processor_registry.enrich_snapshot(snapshot)
        if scraper_movie_nfo.get("basic") or scraper_movie_nfo.get("credits"):
            nfo_path = os.path.join(dir_path, f"{file_name}.nfo")
            if force_nfo or not self._exists(nfo_path):
                self._nfo_gen.gen_movie_nfo_from_snapshot(snapshot, scraper_movie_nfo, dir_path, file_name)
        self._download_snapshot_images(snapshot, dir_path, scraper_movie_pic, force_pic)
        self._normalize_snapshot_poster(snapshot, dir_path)
        if self._dst_backend is None:
            self._apply_watermark(snapshot, dir_path)

    def _scrape_tv_from_snapshot(self, snapshot, media, dir_path, file_name, file_ext, force_nfo, force_pic):
        scraper_tv_nfo = self._scraper_nfo.get("tv", {})
        scraper_tv_pic = self._scraper_pic.get("tv", {})
        season_dir = bool(
            re.match(
                r"^(?:Season|S)\s*\d+$",
                os.path.basename(dir_path.rstrip("/\\")),
                re.IGNORECASE,
            )
        )
        tv_root = os.path.dirname(dir_path) if season_dir else dir_path
        season_number = int(media.get_season_seq() or 1)
        episode_number = int(media.get_episode_seq() or 1)

        if scraper_tv_nfo.get("basic") or scraper_tv_nfo.get("credits"):
            tv_nfo = os.path.join(tv_root, "tvshow.nfo")
            if force_nfo or not self._exists(tv_nfo):
                self._nfo_gen.gen_tv_nfo_from_snapshot(
                    snapshot,
                    scraper_tv_nfo,
                    tv_root,
                    show_title=str(getattr(media, "title", "") or ""),
                )

        season = next((item for item in snapshot.seasons if item.season_number == season_number), None)
        if season is not None and scraper_tv_nfo.get("season_basic"):
            season_nfo = os.path.join(dir_path, "season.nfo")
            if force_nfo or not self._exists(season_nfo):
                self._nfo_gen.gen_season_nfo_from_snapshot(season, season_number, dir_path)

        episode = next(
            (
                item
                for item in snapshot.episodes
                if item.season_number == season_number and item.episode_number == episode_number
            ),
            None,
        )
        if episode is not None and (scraper_tv_nfo.get("episode_basic") or scraper_tv_nfo.get("episode_credits")):
            episode_nfo = os.path.join(dir_path, f"{file_name}.nfo")
            if force_nfo or not self._exists(episode_nfo):
                self._nfo_gen.gen_episode_nfo_from_snapshot(
                    snapshot, episode, scraper_tv_nfo, season_number, dir_path, file_name
                )

        self._download_snapshot_images(snapshot, tv_root, scraper_tv_pic, force_pic)
        if season is not None and scraper_tv_pic.get("season_poster") and season.poster:
            self._downloader.download(
                season.poster,
                dir_path,
                "season{}-poster".format(str(season_number).rjust(2, "0")),
                force_pic,
            )
        if episode is not None and scraper_tv_pic.get("episode_thumb") and episode.still:
            self._downloader.download(episode.still, dir_path, f"{file_name}-thumb", force_pic)

    def _apply_watermark(self, snapshot, target_dir):
        if self._dst_backend is not None:
            return
        scraper_processor_registry.process_watermark(target_dir, snapshot)

    def _normalize_snapshot_poster(self, snapshot, target_dir):
        """宽幅封面先裁右侧 2:3 前封面，再生成 fanart/thumb."""
        if self._dst_backend is not None:
            return
        poster_path = None
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            candidate = os.path.join(target_dir, f"poster{ext}")
            if os.path.exists(candidate):
                poster_path = candidate
                break
        if not poster_path:
            return
        try:
            with Image.open(poster_path) as img:
                width, height = img.size
                if width <= height * 1.15:
                    return
                original = img.copy()
                fanart_path = os.path.join(target_dir, "fanart.jpg")
                if not os.path.exists(fanart_path):
                    original.save(fanart_path, quality=92)
                thumb_path = os.path.join(target_dir, "thumb.jpg")
                if not os.path.exists(thumb_path) or not self._valid_image(target_dir, "thumb", 300, 150):
                    thumb_h = min(height, int(width * 9 / 16))
                    top = max(0, (height - thumb_h) // 2)
                    original.crop((0, top, width, top + thumb_h)).save(thumb_path, quality=90)
            modes = scraper_processor_registry.process_poster(poster_path, snapshot)
            if modes:
                log.info(f"[Scraper]封面裁剪模式 {','.join(modes)}：{poster_path}")
        except Exception as exc:  # noqa: BLE001
            log.warn(f"[Scraper]封面后处理失败 {poster_path}: {exc}")

    def _valid_image(self, target_dir, file_name, min_width, min_height):
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            path = os.path.join(target_dir, f"{file_name}{ext}")
            if not os.path.exists(path):
                continue
            try:
                with Image.open(path) as img:
                    width, height = img.size
                if width >= min_width and height >= min_height:
                    return True
            except Exception as exc:  # noqa: BLE001 - 损坏图片视为无效
                log.debug(f"[Scraper]图片校验失败 {path}: {exc}")
            try:
                os.remove(path)
            except OSError:
                pass
        return False

    def _download_candidates(
        self,
        candidates,
        target_dir,
        file_name,
        force,
        min_width,
        min_height,
        require_portrait=False,
    ):
        for url in candidates:
            if not url or url.rstrip("/").endswith("/login"):
                continue
            try:
                if not self._downloader.download(url, target_dir, file_name, force):
                    continue
                if self._valid_image(target_dir, file_name, min_width, min_height):
                    if require_portrait:
                        path = next(
                            (
                                os.path.join(target_dir, f"{file_name}{ext}")
                                for ext in (".jpg", ".jpeg", ".png", ".webp")
                                if os.path.exists(os.path.join(target_dir, f"{file_name}{ext}"))
                            ),
                            "",
                        )
                        if path:
                            try:
                                with Image.open(path) as img:
                                    if img.height <= img.width:
                                        os.remove(path)
                                        continue
                            except Exception:  # noqa: BLE001 - 损坏图片继续尝试
                                os.remove(path)
                                continue
                    return True
            except Exception as exc:  # noqa: BLE001 - 候选 fallback
                log.debug(f"[Scraper]快照图片候选失败 {url}: {exc}")
        return False

    def _ensure_snapshot_images(self, snapshot) -> None:
        if self._metadata_service is None:
            return
        need_images = not getattr(snapshot, "images", None)
        need_credits = not getattr(snapshot, "credits", None)
        if not need_images and not need_credits:
            return
        for ref in getattr(snapshot, "refs", []) or []:
            provider = str(getattr(ref, "provider", "") or "").strip()
            external_id = str(getattr(ref, "external_id", "") or "").strip()
            if not provider or not external_id:
                continue
            record = self._metadata_service.lookup(
                provider,
                external_id,
                media_type=getattr(ref, "media_type", None),
                content_profile=getattr(snapshot, "content_profile", None),
                allow_private=True,
            )
            if not record:
                continue
            if need_images:
                images = record.get("images") or {}
                snapshot.images = {
                    kind: [ImageAsset(**item) for item in assets]
                    for kind, assets in images.items()
                    if isinstance(assets, list)
                }
            credits = record.get("credits") or []
            if credits and not snapshot.credits:
                snapshot.credits = [Credit(**item) for item in credits]
            extra = record.get("extra") or {}
            if extra:
                snapshot.extra.update(extra)
            return

    def _download_snapshot_images(self, snapshot, target_dir, scraper_pic, force_pic):
        mapping = (("poster", "poster"), ("backdrop", "fanart"), ("logo", "logo"), ("thumb", "thumb"))
        for image_type, file_name in mapping:
            enabled = scraper_pic.get(image_type) or (image_type == "backdrop" and scraper_pic.get("fanart"))
            if not enabled:
                continue
            if image_type == "backdrop":
                candidates = self._images.candidates(snapshot, "fanart") or self._images.candidates(
                    snapshot, "backdrop"
                )
                self._download_candidates(candidates, target_dir, file_name, force_pic, 500, 250)
                continue
            if image_type == "thumb":
                base_candidates = self._images.candidates(snapshot, "thumb")
                if self._download_candidates(base_candidates, target_dir, file_name, force_pic, 300, 150):
                    continue
                fanart_candidates = self._images.candidates(snapshot, "fanart") or self._images.candidates(
                    snapshot, "backdrop"
                )
                self._download_candidates(fanart_candidates, target_dir, file_name, force_pic, 500, 250)
                continue
            candidates = self._images.candidates(snapshot, image_type)
            min_width = 300 if image_type == "poster" else 100
            min_height = 300 if image_type == "poster" else 100
            if image_type == "poster":
                if self._download_candidates(
                    candidates,
                    target_dir,
                    file_name,
                    force_pic,
                    min_width,
                    min_height,
                    require_portrait=True,
                ):
                    continue
                log.info("[Scraper]未找到竖版海报，回退宽幅封面并裁切")
            self._download_candidates(
                candidates,
                target_dir,
                file_name,
                force_pic,
                min_width,
                min_height,
            )
        if scraper_pic.get("actor"):
            self._download_snapshot_actors(snapshot, target_dir, force_pic)

    def _download_snapshot_actors(self, snapshot, target_dir, force_pic):
        actors = self._images.actor_candidates(snapshot)
        if not actors or self._dst_backend is not None:
            return
        actors_dir = os.path.join(target_dir, "actors")
        os.makedirs(actors_dir, exist_ok=True)
        for name, url in actors:
            safe_name = "".join(ch for ch in name if ch not in '\\/:*?"<>|').strip()
            if not safe_name:
                continue
            try:
                self._downloader.download(url, actors_dir, safe_name, force_pic)
            except Exception as exc:  # noqa: BLE001
                log.debug(f"[Scraper]演员图片下载失败 {name}: {exc}")

    def _download_history_tmdb(self, file_path):
        """从下载历史中读取订阅时记录的 TMDB 信息。

        匹配方式：下载历史的 SAVE_PATH 是文件/目录所在路径。
        返回 (tmdbid: int, media_type: str)，未匹配时返回 (None, "")。
        """
        try:
            repo = DownloadHistoryRepositoryAdapter()
            history = repo.get_download_history_by_path(file_path)
            if not history:
                parent = os.path.dirname(file_path)
                if parent and parent != file_path:
                    history = repo.get_download_history_by_path(parent)
            log.debug(f"[Scraper]下载历史查询: {os.path.normpath(file_path)} -> {bool(history)}")
            if history:
                # get_download_history_by_path 返回原始 ORM 对象，字段为大写
                tmdbid = getattr(history, "TMDBID", "") or ""
                mtype = getattr(history, "TYPE", "") or ""
                anchor_provider = getattr(history, "ANCHOR_PROVIDER", None)
                anchor_external = getattr(history, "ANCHOR_EXTERNAL_ID", None)
                if str(tmdbid).startswith("DB:") or str(tmdbid).isdigit() or anchor_provider:
                    return (
                        str(tmdbid)
                        if str(tmdbid).startswith("DB:")
                        else (int(tmdbid) if str(tmdbid).isdigit() else None),
                        mtype,
                        anchor_provider,
                        anchor_external,
                        getattr(history, "CONTENT_PROFILE", None),
                    )
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Scraper]读取下载历史 TMDB 失败: {file_path} - {e}")
        return None, "", None, None, None

    def _extract_tmdbid(self, file_path, meta_info, dst_backend=None):
        """从本地 NFO 文件提取 TMDB ID"""
        if meta_info.type == MediaType.MOVIE:
            movie_nfo = os.path.join(os.path.dirname(file_path), "movie.nfo")
            if dst_backend is not None:
                if dst_backend.exists(movie_nfo):
                    return MediaLibrary.get_tmdbid_from_nfo_remote(movie_nfo, dst_backend)
                file_nfo = os.path.join(os.path.splitext(file_path)[0] + ".nfo")
                if dst_backend.exists(file_nfo):
                    return MediaLibrary.get_tmdbid_from_nfo_remote(file_nfo, dst_backend)
            else:
                if os.path.exists(movie_nfo):
                    return MediaLibrary.get_tmdbid_from_nfo(movie_nfo)
                file_nfo = os.path.join(os.path.splitext(file_path)[0] + ".nfo")
                if os.path.exists(file_nfo):
                    return MediaLibrary.get_tmdbid_from_nfo(file_nfo)
        else:
            tv_nfo = os.path.join(os.path.dirname(os.path.dirname(file_path)), "tvshow.nfo")
            if dst_backend is not None:
                if dst_backend.exists(tv_nfo):
                    return MediaLibrary.get_tmdbid_from_nfo_remote(tv_nfo, dst_backend)
            else:
                if os.path.exists(tv_nfo):
                    return MediaLibrary.get_tmdbid_from_nfo(tv_nfo)
        return None

    def _exists(self, path: str) -> bool:
        """后端感知的存在性检查（远程目标用 dst_backend.exists）"""
        if self._dst_backend is not None:
            try:
                return bool(self._dst_backend.exists(path))
            except Exception:  # noqa: BLE001
                return False
        return os.path.exists(path)

    def gen_scraper_files(
        self, media, dir_path, file_name, file_ext, force=False, force_nfo=False, force_pic=False, dst_backend=None
    ):
        """刮削元数据入口"""
        # 单例在启动时只加载一次配置，这里每次刮削前重新读取，保证运行期配置变更生效
        self._init_config()
        if not force and not self._scraper_flag:
            log.warn("[Scraper]刮削标志未启用，跳过")
            return
        if not self._scraper_nfo and not self._scraper_pic:
            log.warn("[Scraper]刮削配置为空，跳过")
            return
            return
        self._scraper_nfo = self._scraper_nfo or {}
        self._scraper_pic = self._scraper_pic or {}
        self._dst_backend = dst_backend
        self._downloader.set_dst_backend(dst_backend)
        log.info(
            f"[Scraper]开始生成刮削文件：dir={dir_path}, file={file_name}, "
            f"type={media.type}, backend={dst_backend is not None}, "
            f"nfo_keys={list(self._scraper_nfo.keys())}, pic_keys={list(self._scraper_pic.keys())}"
        )

        try:
            video_path = os.path.join(dir_path, f"{file_name}{file_ext}")
            if not os.path.exists(video_path):
                candidates = (
                    [
                        os.path.join(dir_path, item)
                        for item in os.listdir(dir_path)
                        if item.startswith(file_name)
                        and item.lower().endswith((".mp4", ".mkv", ".avi", ".wmv", ".ts", ".m2ts"))
                    ]
                    if os.path.isdir(dir_path)
                    else []
                )
                video_path = candidates[0] if candidates else ""
            profile_media = self._profile_media_info(video_path) if video_path else None
            if profile_media is not None and self._metadata_service is not None:
                snapshot = self._metadata_service.compose_for_media(profile_media, with_episodes=True, persist=True)
                if snapshot is not None:
                    self.gen_snapshot_files(
                        snapshot=snapshot,
                        media=profile_media,
                        dir_path=dir_path,
                        file_name=file_name,
                        file_ext=file_ext,
                        force_nfo=force_nfo,
                        force_pic=force_pic,
                        dst_backend=dst_backend,
                    )
                    log.info(f"[Scraper]{file_name} 插件画像快照刮削完成")
                    return
            if media.type == MediaType.MOVIE:
                self._scrape_movie(media, dir_path, file_name, force_nfo, force_pic)
            else:
                self._scrape_tv(media, dir_path, file_name, file_ext, force_nfo, force_pic)
            log.info(f"[Scraper]刮削文件生成完成：{file_name}")
        except Exception as e:
            log.error(f"[Scraper]刮削文件生成失败：{file_name}，错误：{e}")
            ExceptionUtils.exception_traceback(e)

    def _scrape_movie(self, media, dir_path, file_name, force_nfo, force_pic):
        """刮削电影元数据 — 各步骤独立容错，单步失败不影响其他刮削输出."""
        scraper_movie_nfo = self._scraper_nfo.get("movie", {})
        scraper_movie_pic = self._scraper_pic.get("movie", {})

        if scraper_movie_nfo.get("basic") or scraper_movie_nfo.get("credits"):
            nfo_exists = self._exists(os.path.join(dir_path, "movie.nfo")) or self._exists(
                os.path.join(dir_path, f"{file_name}.nfo")
            )
            if force_nfo or not nfo_exists:
                try:
                    doubaninfo = self._fetch_douban(media, scraper_movie_nfo)
                    directors, actors = self._fetch_credits(media.provider_data, scraper_movie_nfo, doubaninfo)
                    self._nfo_gen.gen_movie_nfo(
                        media.provider_data, directors, actors, scraper_movie_nfo, dir_path, file_name
                    )
                except Exception as e:
                    log.error(f"[Scraper]生成 movie.nfo 失败：{e}")

        try:
            self._download_images(media, dir_path, scraper_movie_pic, force_pic)
        except Exception as e:
            log.error(f"[Scraper]下载电影图片失败：{e}")

    def _scrape_tv(self, media, dir_path, file_name, file_ext, force_nfo, force_pic):
        """刮削电视剧元数据 — 各步骤独立容错，单步失败不影响其他刮削输出."""
        scraper_tv_nfo = self._scraper_nfo.get("tv", {})
        scraper_tv_pic = self._scraper_pic.get("tv", {})
        season_dir = bool(
            re.match(
                r"^(?:Season|S)\s*\d+$",
                os.path.basename(dir_path.rstrip("/\\")),
                re.IGNORECASE,
            )
        )
        tv_root = os.path.dirname(dir_path) if season_dir else dir_path

        # ---- tvshow.nfo ----
        if force_nfo or not self._exists(os.path.join(tv_root, "tvshow.nfo")):
            if scraper_tv_nfo.get("basic") or scraper_tv_nfo.get("credits"):
                try:
                    doubaninfo = self._fetch_douban(media, scraper_tv_nfo)
                    directors, actors = self._fetch_credits(media.provider_data, scraper_tv_nfo, doubaninfo)
                    self._nfo_gen.gen_tv_nfo(media.provider_data, directors, actors, scraper_tv_nfo, tv_root)
                except Exception as e:
                    log.error(f"[Scraper]生成 tvshow.nfo 失败：{e}")

        # ---- tv 图片 ----
        try:
            self._download_tv_images(media, tv_root, scraper_tv_pic, force_pic)
        except Exception as e:
            log.error(f"[Scraper]下载 TV 图片失败：{e}")

        # ---- 季/集详情 ----
        need_season_detail = (
            scraper_tv_nfo.get("season_basic")
            or scraper_tv_nfo.get("episode_basic")
            or scraper_tv_nfo.get("episode_credits")
            or scraper_tv_pic.get("season_poster")
        )
        seasoninfo = None
        if need_season_detail:
            try:
                seasoninfo = self.media.get_tmdb_tv_season_detail(
                    tmdbid=media.tmdb_id, season=int(media.get_season_seq())
                )
            except Exception as e:
                log.error(f"[Scraper]获取季详情失败：{e}")

        # ---- season.nfo ----
        if scraper_tv_nfo.get("season_basic"):
            if force_nfo or not self._exists(os.path.join(dir_path, "season.nfo")):
                if seasoninfo:
                    try:
                        self._nfo_gen.gen_season_nfo(seasoninfo, int(media.get_season_seq()), dir_path)
                    except Exception as e:
                        log.error(f"[Scraper]生成 season.nfo 失败：{e}")

        # ---- episode.nfo ----
        if scraper_tv_nfo.get("episode_basic") or scraper_tv_nfo.get("episode_credits"):
            if force_nfo or not self._exists(os.path.join(dir_path, f"{file_name}.nfo")):
                if seasoninfo:
                    try:
                        self._nfo_gen.gen_episode_nfo(
                            seasoninfo,
                            scraper_tv_nfo,
                            int(media.get_season_seq()),
                            int(media.get_episode_seq()),
                            dir_path,
                            file_name,
                        )
                    except Exception as e:
                        log.error(f"[Scraper]生成 episode nfo 失败：{e}")

        # ---- season poster ----
        if scraper_tv_pic.get("season_poster"):
            try:
                season_poster = "season{}-poster".format(media.get_season_seq().rjust(2, "0"))
                seasonposter = self.fanart.get_seasonposter(
                    media_type=media.type, queryid=media.tvdb_id, season=media.get_season_seq()
                )
                if seasonposter:
                    self._downloader.download(seasonposter, dir_path, season_poster, force_pic)
                elif seasoninfo:
                    self._downloader.download(
                        ImageProxy.get_tmdbimage_url(seasoninfo.get("poster_path"), prefix="original", use_proxy=False),
                        dir_path,
                        season_poster,
                        force_pic,
                    )
            except Exception as e:
                log.error(f"[Scraper]下载 season poster 失败：{e}")

        # ---- season banner ----
        if scraper_tv_pic.get("season_banner"):
            try:
                seasonbanner = self.fanart.get_seasonbanner(
                    media_type=media.type, queryid=media.tvdb_id, season=media.get_season_seq()
                )
                if seasonbanner:
                    self._downloader.download(
                        seasonbanner,
                        tv_root,
                        "season{}-banner".format(media.get_season_seq().rjust(2, "0")),
                        force_pic,
                    )
            except Exception as e:
                log.error(f"[Scraper]下载 season banner 失败：{e}")

        # ---- season thumb ----
        if scraper_tv_pic.get("season_thumb"):
            try:
                seasonthumb = self.fanart.get_seasonthumb(
                    media_type=media.type, queryid=media.tvdb_id, season=media.get_season_seq()
                )
                if seasonthumb:
                    self._downloader.download(
                        seasonthumb,
                        tv_root,
                        "season{}-landscape".format(media.get_season_seq().rjust(2, "0")),
                        force_pic,
                    )
            except Exception as e:
                log.error(f"[Scraper]下载 season thumb 失败：{e}")

        # ---- episode thumb ----
        if scraper_tv_pic.get("episode_thumb"):
            try:
                episode_thumb = os.path.join(dir_path, file_name + "-thumb.jpg")
                if force_pic or not self._exists(episode_thumb):
                    episode_image = self.media.get_episode_images(
                        tv_id=media.tmdb_id,
                        season_id=media.get_season_seq(),
                        episode_id=media.get_episode_seq(),
                        orginal=True,
                    )
                    if episode_image:
                        self._downloader.download(episode_image, episode_thumb, "", force_pic)
                    elif scraper_tv_pic.get("episode_thumb_ffmpeg"):
                        video_path = os.path.join(dir_path, file_name + file_ext)
                        log.info(f"[Scraper]正在生成缩略图：{video_path} ...")
                        FfmpegProcessor().get_thumb_image_from_video(video_path=video_path, image_path=episode_thumb)
                        log.info(f"[Scraper]缩略图生成完成：{episode_thumb}")
            except Exception as e:
                log.error(f"[Scraper]下载 episode thumb 失败：{e}")

    def _fetch_douban(self, media, scraper_nfo):
        """获取豆瓣信息（用于中文演职人员）"""
        if scraper_nfo.get("credits") and scraper_nfo.get("credits_chinese"):
            return self.douban.get_douban_info(media)
        return None

    def _fetch_credits(self, tmdbinfo, scraper_nfo, doubaninfo):
        """获取导演/演员列表，可选中文匹配"""
        if not scraper_nfo.get("credits"):
            return [], []
        directors, actors = self.media.get_tmdb_directors_actors(tmdbinfo=tmdbinfo)
        if scraper_nfo.get("credits_chinese") and doubaninfo:
            directors, actors = self._credits.match(directors, actors, doubaninfo)
        return directors, actors

    def _download_images(self, media, dir_path, scraper_pic, force_pic):
        """下载电影图片"""
        if scraper_pic.get("poster"):
            poster = media.get_poster_image(original=True)
            if poster:
                self._downloader.download(poster, dir_path, "poster", force_pic)
        if scraper_pic.get("backdrop"):
            backdrop = media.get_backdrop_image(default=False, original=True)
            if backdrop:
                self._downloader.download(backdrop, dir_path, "fanart", force_pic)
        for pic_type in ["background", "logo", "disc", "banner", "thumb"]:
            if scraper_pic.get(pic_type):
                getter = getattr(self.fanart, f"get_{pic_type}", None)
                if getter:
                    url = getter(media_type=media.type, queryid=media.tmdb_id)
                    if url:
                        self._downloader.download(url, dir_path, pic_type, force_pic)

    def _download_tv_images(self, media, tv_root, scraper_pic, force_pic):
        """下载电视剧图片"""
        if scraper_pic.get("poster"):
            poster = media.get_poster_image(original=True)
            if poster:
                self._downloader.download(poster, tv_root, "poster", force_pic)
        if scraper_pic.get("backdrop"):
            backdrop = media.get_backdrop_image(default=False, original=True)
            if backdrop:
                self._downloader.download(backdrop, tv_root, "fanart", force_pic)
        for pic_type in ["background", "logo", "disc", "banner", "thumb"]:
            if scraper_pic.get(pic_type):
                getter = getattr(self.fanart, f"get_{pic_type}", None)
                if getter:
                    url = getter(media_type=media.type, queryid=media.tvdb_id)
                    if url:
                        self._downloader.download(url, tv_root, pic_type, force_pic)
