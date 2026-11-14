"""
DoubanRank Plugin v2
监控豆瓣热门榜单，自动添加订阅
"""

import re
from datetime import datetime
from threading import Event

import defusedxml.minidom  # type: ignore[import-untyped]

import log
from app.domain.enums import SearchType
from app.domain.media_types import ProviderMediaType
from app.infrastructure.http.client import HttpClient
from app.mediaserver.media_server import MediaServer
from app.plugin_framework.builtin_plugins._ms_common.mediaserver_lifecycle import resolve_plugin_server_id
from app.plugin_framework.context import PluginContext
from app.services.rss_processor import RssHelper
from app.services.subscribe_service import SubscribeService
from app.services.web.utils import get_mediainfo_from_id
from app.utils import DomUtils
from app.utils.json_utils import JsonUtils


class DoubanRankPlugin:
    """豆瓣榜单订阅插件"""

    def __init__(
        self,
        ctx: PluginContext,
        mediaserver: MediaServer,
        subscribe: SubscribeService,
    ):
        self.ctx = ctx
        self._mediaserver = mediaserver
        self._subscribe = subscribe
        self._rsshelper = RssHelper(site_engine=ctx.site_engine)
        self._media = self.ctx.media_service
        self._event = Event()
        self._douban_address = {
            "movie-ustop": "https://rsshub.app/douban/movie/ustop",
            "movie-weekly": "https://rsshub.app/douban/movie/weekly",
            "movie-real-time": "https://rsshub.app/douban/movie/weekly/subject_real_time_hotest",
            "show-domestic": "https://rsshub.app/douban/movie/weekly/show_domestic",
            "movie-hot-gaia": "https://rsshub.app/douban/movie/weekly/movie_hot_gaia",
            "tv-hot": "https://rsshub.app/douban/movie/weekly/tv_hot",
            "movie-top250": "https://rsshub.app/douban/movie/weekly/movie_top250",
        }

    # 剧集类榜单标记：URL 或 rank 名里出现即按剧集处理，其余按电影
    _TV_ADDR_MARKERS = ("tv_hot", "show_domestic", "/tv", "show-", "tv-")

    @classmethod
    def _infer_type_from_addr(cls, addr: str) -> ProviderMediaType | None:
        """从榜单地址推断媒体类型。

        RSS 条目里没有类型字段，之前 `rss_info.get("type")` 恒为 None，
        交给元数据网关时类型未知，豆瓣条目可能被当成另一种形态解析。
        """
        text = str(addr or "").lower()
        if not text:
            return None
        return ProviderMediaType.SERIES if any(m in text for m in cls._TV_ADDR_MARKERS) else ProviderMediaType.MOVIE

    @staticmethod
    def _min_year(year_limit: int) -> int:
        """允许订阅的最早年份：近 N 年（含今年）。

        year_limit=2 → 今年与去年。榜单里的老片多半是识别错作品，或者老片
        重置版（发行年仍是原年份），按年份直接挡掉，不给错误订阅的机会。
        """
        return datetime.now().year - max(int(year_limit), 1) + 1

    def _get_config(self):
        return self.ctx.get_config() or {}

    def on_enable(self):
        self.ctx.info("豆瓣榜单订阅插件已启用")
        self._start_service()

    def on_disable(self):
        self.ctx.info("豆瓣榜单订阅插件已禁用")
        self._stop_service()

    def on_hook(self, event, data):
        if event == "plugin.config_changed":
            if data.get("plugin_id") == self.ctx.plugin_id:
                self.ctx.info("配置已变更，重载服务")
                self._stop_service()
                self._start_service()

    def run(self):
        """立即运行刷新"""
        self.ctx.info("手动触发豆瓣榜单刷新")
        self._refresh_rss(manual=True)

    def _start_service(self):
        config = self._get_config()
        enable = config.get("enable", False)
        cron = config.get("cron")

        if not enable:
            return

        if cron:
            self.ctx.info(f"订阅服务启动，周期：{cron}")
            self.ctx.schedule_cron("refresh", self._refresh_rss, cron=str(cron))

    def _stop_service(self):
        self._event.set()
        try:
            self.ctx.remove_schedule("refresh")
            self.ctx.remove_schedule("refresh_once")
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Plugin]忽略异常: {e}")
        self._event.clear()

    def _load_history(self):
        content = self.ctx.read_data("history.json")
        if content:
            try:
                return JsonUtils.loads(content)
            except Exception as e:  # noqa: BLE001
                log.debug(f"[Plugin]忽略异常: {e}")
        return {}

    def _save_history(self, data):
        self.ctx.write_data("history.json", JsonUtils.dumps(data, ensure_ascii=False, indent=2))

    def _update_history(self, media, state):
        if not media:
            return
        data = self._load_history()
        anchor = str(getattr(media, "anchor_external_id", "") or "")
        ref_id = (
            f"DB:{anchor}"
            if getattr(media, "anchor_provider", "") == "douban" and anchor
            else f"BG:{anchor}"
            if getattr(media, "anchor_provider", "") == "bangumi" and anchor
            else str(media.tmdb_id or "")
        )
        data[ref_id or str(media.title or "")] = {
            "id": ref_id or str(media.title or ""),
            "name": media.title,
            "year": media.year,
            "type": media.type.value if hasattr(media.type, "value") else str(media.type),
            "rating": media.vote_average or 0,
            "image": media.get_poster_image() if hasattr(media, "get_poster_image") else "",
            "state": state,
            "add_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._save_history(data)

    def _refresh_rss(self, manual=False):
        config = self._get_config()
        enable = config.get("enable", False)
        vote = float(config.get("vote") or 0) if config.get("vote") else 0
        rss_addrs = config.get("rss_addrs", [])
        ranks = config.get("ranks", [])
        # 只订阅近 N 年发行的内容；未配置时默认 2 年。
        # 榜单上的老片要么是识别成错作品，要么是老片重置版，都不该自动订阅。
        year_limit = int(config.get("year_limit") or 2)
        min_year = self._min_year(year_limit)

        if not enable and not manual:
            return

        if isinstance(rss_addrs, str):
            rss_addrs = [a for a in rss_addrs.split("\n") if a]

        addr_list = rss_addrs + [self._douban_address.get(rank) for rank in ranks]
        if not addr_list:
            self.ctx.info("未设置RSS地址")
            return

        self.ctx.info(f"共 {len(addr_list)} 个RSS地址需要刷新")
        for addr in addr_list:
            if not addr:
                continue
            try:
                self.ctx.info(f"获取RSS：{addr} ...")
                rss_infos = self._get_rss_info(addr)
                if not rss_infos:
                    self.ctx.error(f"RSS地址：{addr} ，未查询到数据")
                    continue

                self.ctx.info(f"RSS地址：{addr} ，共 {len(rss_infos)} 条数据")
                for rss_info in rss_infos:
                    if self._event.is_set():
                        self.ctx.info("订阅服务停止")
                        return

                    title = rss_info.get("title")
                    douban_id = rss_info.get("doubanid")
                    douban_year = str(rss_info.get("douban_year") or "").strip()
                    # RSS 条目没有类型字段，按榜单地址推断，避免类型未知导致错解析
                    mtype = self._infer_type_from_addr(addr)
                    unique_flag = f"doubanrank: {title} (DB:{douban_id})"

                    # 豆瓣年份就是这条榜单内容的真实年份。榜单本身只会推近期内容，
                    # 因此解析不出豆瓣 ID 时宁可跳过，也不要用标题裸搜 TMDB ——
                    # 裸搜会撞上同名老片，订阅并下载完全无关的旧作。
                    if not douban_id:
                        self.ctx.info(f"{title} 未解析到豆瓣 ID，跳过（避免标题误配同名作品）")
                        continue

                    if douban_year.isdigit() and int(douban_year) < min_year:
                        self.ctx.info(f"{title} 豆瓣年份 {douban_year} 早于 {min_year}，跳过")
                        continue

                    if self._rsshelper.is_rssd_by_simple(torrent_name=unique_flag, enclosure=None):
                        self.ctx.info(f"已处理过：{title}")
                        continue

                    media_info = get_mediainfo_from_id(mtype=mtype, mediaid=f"DB:{douban_id}", wait=True)

                    if not media_info:
                        self.ctx.warn(f"未查询到媒体信息：{title}")
                        continue

                    if vote and media_info.vote_average and media_info.vote_average < vote:
                        self.ctx.info(f"{media_info.get_title_string()} 评分低于限制，跳过")
                        continue

                    # 发行年份守门：榜单里的老片要么识别成了错作品，要么是老片重置版。
                    # 拿不到年份同样跳过——无法保证是近期内容时，宁可不错订阅。
                    raw_year = str(media_info.year or "").strip()
                    if not raw_year.isdigit():
                        self.ctx.info(f"{title} 未取到发行年份，跳过（无法确认是近期内容）")
                        continue
                    if int(raw_year) < min_year:
                        self.ctx.info(
                            f"{media_info.get_title_string()} 发行年 {raw_year} 早于 {min_year}"
                            f"（近 {year_limit} 年），跳过"
                        )
                        continue
                    # 豆瓣年份与元数据年份相差过大，说明元数据抓到了另一部作品
                    if douban_year.isdigit() and abs(int(raw_year) - int(douban_year)) > 1:
                        self.ctx.info(
                            f"{title} 元数据年份 {raw_year} 与豆瓣年份 {douban_year} 不符，"
                            f"疑似识别成其它作品，跳过"
                        )
                        continue

                    item_id = self._mediaserver.check_item_exists(
                        mtype=media_info.type,
                        title=media_info.title,
                        year=media_info.year,
                        tmdbid=media_info.tmdb_id,
                        season=media_info.get_season_seq(),
                        server_id=resolve_plugin_server_id(
                            self._mediaserver,
                            self._get_config(),
                            content_profile=media_info.content_profile,
                        ),
                    )
                    if item_id:
                        self.ctx.info(f"媒体服务器已存在：{media_info.get_title_string()}")
                        self._update_history(media=media_info, state="DOWNLOADED")
                        continue

                    if self._subscribe.check_history(
                        type_str="movie" if media_info.type == ProviderMediaType.MOVIE else "tv",
                        name=media_info.title or "",
                        year=media_info.year,
                        season=media_info.get_season_string(),
                    ):
                        self.ctx.info(f"{media_info.get_title_string()} 已订阅过")
                        self._update_history(media=media_info, state="RSS")
                        continue

                    self._rsshelper.simple_insert_rss_torrents(title=unique_flag, enclosure=None)
                    code, msg, rss_media = self._subscribe.add_rss_subscribe(
                        mtype=media_info.type,
                        name=media_info.title,
                        year=media_info.year,
                        season=media_info.begin_season,
                        channel="auto",
                        in_from=str(SearchType.PLUGIN.value),
                    )
                    if not rss_media or code != 0:
                        self.ctx.warn(f"{media_info.get_title_string()} 添加订阅失败：{msg}")
                        if code == 9:
                            self._update_history(media=media_info, state="RSS")
                    else:
                        self.ctx.info(f"{media_info.get_title_string()} 添加订阅成功")
                        self._update_history(media=media_info, state="RSS")
            except Exception as e:
                self.ctx.error(str(e))
        self.ctx.info("所有RSS刷新完成")

    # 豆瓣条目 ID：取 link 结尾的纯数字段。
    # RSSHub 给的是 `https://www.douban.com/doubanapp/dispatch/movie/36847425`，
    # 数字后面没有斜杠；旧正则 `/(\d+)/` 要求两侧都是斜杠，永远匹配不到，
    # 于是 doubanid 恒为空，只能改用标题去 TMDB 裸搜，同名老片被当成本条榜单
    # 内容订阅下来 —— 这就是「订阅的和下载的不是一个东西」的根因。
    _DOUBAN_ID_RE = re.compile(r"/(\d{3,})(?:[/?#].*)?$")
    # 榜单描述里的发行年：`标签：2026 / 韩国 / 剧情`，是豆瓣自己的年份
    _DOUBAN_YEAR_RE = re.compile(r"标签\s*[:：]\s*(\d{4})")

    @classmethod
    def _parse_douban_id(cls, link: str) -> str:
        match = cls._DOUBAN_ID_RE.search(str(link or "").strip())
        return match.group(1) if match else ""

    @classmethod
    def _parse_douban_year(cls, description: str) -> str:
        match = cls._DOUBAN_YEAR_RE.search(str(description or ""))
        return match.group(1) if match else ""

    @staticmethod
    def _get_rss_info(addr):
        try:
            ret = HttpClient().get(addr)
            if not ret:
                return []

            ret_xml = ret.text
            ret_array = []
            dom_tree = defusedxml.minidom.parseString(ret_xml)
            root_node = dom_tree.documentElement
            if not root_node:
                return ret_array
            items = root_node.getElementsByTagName("item")
            for item in items:
                try:
                    title = DomUtils.tag_value(item, "title", default="")
                    link = DomUtils.tag_value(item, "link", default="")
                    desc = DomUtils.tag_value(item, "description", default="")
                    if not title and not link:
                        continue
                    ret_array.append(
                        {
                            "title": title,
                            "link": link,
                            "doubanid": DoubanRankPlugin._parse_douban_id(link),
                            "douban_year": DoubanRankPlugin._parse_douban_year(desc),
                        }
                    )
                except Exception as e:  # noqa: BLE001
                    log.debug(f"[DoubanRank]解析 RSS 条目失败: {e}")
                    continue
            return ret_array
        except Exception as e:  # noqa: BLE001
            log.debug(f"[DoubanRank]解析 RSS 失败: {e}")
            return []
