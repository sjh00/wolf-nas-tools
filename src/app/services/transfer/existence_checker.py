"""MediaExistenceChecker - 媒体文件存在性检查."""

import os

import log
from app.core.constants import RMT_FAVTYPE, RMT_MEDIAEXT
from app.domain.media_types import ProviderMediaType
from app.services.transfer.path_resolver import safe_category_name
from app.utils import PathUtils


class MediaExistenceChecker:
    """负责检查媒体文件是否已存在于目标目录（支持本地和远程后端）."""

    def __init__(self, path_resolver, media_service=None):
        self._path_resolver = path_resolver
        self._media = media_service

    @staticmethod
    def _layout_dirs(base: str, dir_name: str, category: str, use_category: bool) -> list[str]:
        """布局候选路径，按优先级排列：第 0 项即「新条目应该落在哪里」。

        分类为空时只有平铺；分类存在时有分类/平铺两种写法，由 use_category
        决定首选，另一个作为历史布局的兼容候选。
        """
        flat = os.path.join(base, dir_name)
        if not category:
            return [flat]
        categorized = os.path.join(base, category, dir_name)
        return [categorized, flat] if use_category else [flat, categorized]

    def _exists(self, path: str, backend_id: str = "local") -> bool:
        """根据后端检查路径是否存在."""
        if backend_id == "local":
            return os.path.exists(path)
        backend = self._path_resolver.resolve_backend_by_id(backend_id)
        if not backend:
            return False
        return backend.exists(path)

    def exists(self, path: str, backend_id: str = "local") -> bool:
        """公开的存在性检查（支持本地/远程后端）."""
        return self._exists(path, backend_id)

    def _get_dir_files(self, path: str, backend_id: str = "local", exts: str | list | None = None) -> list[str]:
        """根据后端获取目录下匹配扩展名的文件列表."""
        if not path:
            return []
        _exts = exts or ""
        if backend_id == "local":
            return PathUtils.get_dir_files(path, _exts)
        backend = self._path_resolver.resolve_backend_by_id(backend_id)
        if not backend:
            return []
        files = []
        try:
            for finfo in backend.list_dir(path):
                if finfo.is_dir:
                    continue
                if exts:
                    ext = os.path.splitext(finfo.path)[1].lower()
                    if ext not in exts:
                        continue
                files.append(finfo.path)
        except Exception as e:  # noqa: BLE001
            # 不静默：远程后端列举失败会被下游当成「目录下没有媒体文件」而跳过转移，
            # 只记 debug 会让真实文件长期不转移且无从排查
            log.warn(f"[FileTransfer]远程目录列举失败，本次按空目录处理（可能导致漏转移）：{path} - {e}")
        return files

    @staticmethod
    def _target_names(meta_info_obj) -> set[str]:
        """用于比对文件名与作品名的候选名（兼容多语言）."""
        names = {
            (meta_info_obj.cn_name or "").strip(),
            (meta_info_obj.en_name or "").strip(),
            (meta_info_obj.title or "").strip(),
        }
        names.discard("")
        return names

    def _episodes_from_files(self, files: list[str], meta_info_obj, meta_info_fn, season) -> set[int]:
        """从媒体文件名里解析出属于该季、该作品的集号."""
        episodes: set[int] = set()
        target_names = self._target_names(meta_info_obj)
        for file in files:
            file_meta_info = meta_info_fn(title=os.path.basename(file))
            if not file_meta_info.get_season_list() or not file_meta_info.get_episode_list():
                continue
            file_name = (file_meta_info.get_name() or "").strip()
            if file_name and not any(
                fn == tn or fn in tn or tn in fn for tn in target_names for fn in [file_name]
            ):
                continue
            if not file_meta_info.is_in_season(season):
                continue
            episodes.update(int(ep) for ep in file_meta_info.get_episode_list() if str(ep).isdigit())
        return episodes

    def _list_subdirs(self, path: str, backend_id: str = "local") -> list[str]:
        """列出一级子目录（用于在未知分类的情况下查找剧集目录）."""
        if not path:
            return []
        if backend_id == "local":
            try:
                return [
                    os.path.join(path, name)
                    for name in os.listdir(path)
                    if os.path.isdir(os.path.join(path, name))
                ]
            except OSError:
                return []
        backend = self._path_resolver.resolve_backend_by_id(backend_id)
        if not backend:
            return []
        try:
            return [finfo.path for finfo in backend.list_dir(path) if finfo.is_dir]
        except Exception as e:  # noqa: BLE001
            log.debug(f"[FileTransfer]列举子目录失败 {path}: {e}")
            return []

    def find_season_episodes(self, meta_info_obj, meta_info_fn, season) -> set[int]:
        """找出剧集库中该作品某季已存在的集号，不依赖分类是否已知.

        转移/入库时 media_info 带有分类，可以直接拼出目录；但订阅刚创建时分类可能
        还没解析出来，甚至与入库时不一致。这里在根目录和「根/任意分类」两种布局下
        都找一遍，避免因为目录不同而把整季判定成"本地没有"。

        季目录名与文件命名格式由路径解析器按 `media_info.begin_season` 生成，
        因此 `season` 只用于季判定，不参与拼路径。
        """
        dir_name, season_dir_name, _ = self._path_resolver.get_tv_dest_path(meta_info_obj, self._media)
        if not dir_name or not season_dir_name:
            return set()
        if meta_info_obj.type == ProviderMediaType.ANIME:
            dest_paths = self._path_resolver.anime_path
            backends = self._path_resolver._anime_backend or []
        else:
            dest_paths = self._path_resolver.tv_path
            backends = self._path_resolver._tv_backend or []

        found: set[int] = set()
        for idx, dest_path in enumerate(dest_paths):
            backend_id = backends[idx] if idx < len(backends) else "local"
            candidates = [os.path.join(dest_path, dir_name)]
            for sub_dir in self._list_subdirs(dest_path, backend_id):
                if os.path.basename(sub_dir) == dir_name:
                    continue
                candidates.append(os.path.join(sub_dir, dir_name))
            for media_dir in candidates:
                season_dir = os.path.join(media_dir, season_dir_name)
                if not self._exists(season_dir, backend_id):
                    continue
                files = self._get_dir_files(season_dir, backend_id, RMT_MEDIAEXT)
                if files:
                    found |= self._episodes_from_files(files, meta_info_obj, meta_info_fn, season)
        return found

    def is_media_exists(self, media_dest, media, dst_backend=None):
        """
        判断媒体文件是否已存在.
        :return: (dir_exist_flag, ret_dir_path, file_exist_flag, ret_file_path)
        """
        backend = dst_backend

        def _exists(path: str) -> bool:
            if backend is not None:
                return backend.exists(path)
            return os.path.exists(path)

        dir_exist_flag = False
        file_exist_flag = False
        ret_dir_path = None
        ret_file_path = None

        if media.type == ProviderMediaType.MOVIE:
            dir_name, file_name = self._path_resolver.get_movie_dest_path(media, self._media)
            category = safe_category_name(getattr(media, "category", ""))
            layout_dirs = self._layout_dirs(
                media_dest, dir_name, category, bool(self._path_resolver.movie_category_flag)
            )
            # 新文件始终落主布局；精选目录和旧布局只用于发现已存在的文件
            ret_dir_path = layout_dirs[0]
            ret_file_path = os.path.join(ret_dir_path, file_name)
            for file_path in [os.path.join(media_dest, RMT_FAVTYPE, dir_name), *layout_dirs]:
                file_dest = os.path.join(file_path, file_name)
                found = None
                for ext in RMT_MEDIAEXT:
                    ext_dest = f"{file_dest}{ext}"
                    if _exists(ext_dest):
                        found = ext_dest
                        break
                if found:
                    file_exist_flag = True
                    ret_dir_path = file_path
                    ret_file_path = found
                    break
            dir_exist_flag = _exists(ret_dir_path)
        else:
            dir_name, season_name, file_name = self._path_resolver.get_tv_dest_path(media, self._media)
            # 与 TransferPathResolver.get_dest_path_by_info 使用同一套布局开关。
            category = safe_category_name(getattr(media, "category", ""))
            add_category = bool(self._path_resolver.tv_category_flag)
            if media.type == ProviderMediaType.ANIME:
                add_category = bool(self._path_resolver.anime_category_flag)
            layout_dirs = self._layout_dirs(media_dest, dir_name, category, add_category)
            # 新文件始终落主布局；旧布局只用于发现已存在的文件
            ret_dir_path = os.path.join(layout_dirs[0], season_name)
            if media.get_episode_list():
                ret_file_path = os.path.join(ret_dir_path, file_name)
                for media_path in layout_dirs:
                    season_dir = os.path.join(media_path, season_name)
                    file_path = os.path.join(season_dir, file_name)
                    found = None
                    for ext in RMT_MEDIAEXT:
                        ext_dest = f"{file_path}{ext}"
                        if _exists(ext_dest):
                            found = ext_dest
                            break
                    if found:
                        file_exist_flag = True
                        ret_dir_path = season_dir
                        ret_file_path = found
                        break
            dir_exist_flag = _exists(ret_dir_path)
        return dir_exist_flag, ret_dir_path, file_exist_flag, ret_file_path

    @classmethod
    def _find_existing_file(cls, dir_path: str, file_name: str, exists_fn) -> tuple[str | None, bool]:
        """在给定目录里按媒体扩展名找已存在的同名文件，返回（文件路径, 是否存在）."""
        if not dir_path or not file_name:
            return None, False
        base = os.path.join(dir_path, file_name)
        for ext in RMT_MEDIAEXT:
            candidate = f"{base}{ext}"
            if exists_fn(candidate):
                return candidate, True
        return base, False

    @classmethod
    def _pick_target_dir(cls, candidates: list[str], preferred: str, file_name: str, exists_fn) -> str | None:
        """从布局候选中挑出本次要写入的目录。

        - 某个候选里已有该文件 → 用它，避免同一部片在分类/平铺两种布局各存一份
        - 否则用第一个已存在的目录，让新集数跟已有集数落在同一处
        - 都不存在 → 用首选布局（`candidates` 的首选项），这是新条目该落的目录

        早期实现直接在循环里把 `ret_dir_path` 逐项覆盖，循环结束（没有命中文件时）
        会停在最后一个候选即「平铺」布局——分类布局因此只对库里已存在的条目生效，
        新订阅/新入库的条目全部落到平铺目录，且一旦落错后续集数会一直跟随。
        """
        first_existing: str | None = None
        for path in candidates:
            if not path:
                continue
            if file_name:
                _, hit = cls._find_existing_file(path, file_name, exists_fn)
                if hit:
                    return path
            if first_existing is None and exists_fn(path):
                first_existing = path
        return first_existing or preferred

    def get_no_exists_medias(self, meta_info_obj, meta_info_fn, season=None, total_num=None):
        """
        根据媒体库目录结构，判断媒体是否存在.
        :return: 电影返回已存在的电影清单，剧集返回不存在的集的清单.
        """
        if meta_info_obj.type == ProviderMediaType.MOVIE:
            dir_name, _ = self._path_resolver.get_movie_dest_path(meta_info_obj, self._media)
            backends = self._path_resolver._movie_backend or []
            for idx, dest_path in enumerate(self._path_resolver.movie_path):
                backend_id = backends[idx] if idx < len(backends) else "local"
                fav_path = os.path.join(dest_path, RMT_FAVTYPE, dir_name)
                fav_files = self._get_dir_files(fav_path, backend_id, RMT_MEDIAEXT)
                category = safe_category_name(getattr(meta_info_obj, "category", ""))
                for check_path in self._layout_dirs(
                    dest_path, dir_name, category, bool(self._path_resolver.movie_category_flag)
                ):
                    files = self._get_dir_files(check_path, backend_id, RMT_MEDIAEXT)
                    if len(files) > 0 or len(fav_files) > 0:
                        return [{"title": meta_info_obj.title, "year": meta_info_obj.year}]
            return []
        else:
            dir_name, season_name, _ = self._path_resolver.get_tv_dest_path(meta_info_obj, self._media)
            if not season or not total_num:
                return []
            if meta_info_obj.type == ProviderMediaType.ANIME:
                dest_paths = self._path_resolver.anime_path
                category_flag = self._path_resolver.anime_category_flag
                backends = self._path_resolver._anime_backend or []
            else:
                dest_paths = self._path_resolver.tv_path
                category_flag = self._path_resolver.tv_category_flag
                backends = self._path_resolver._tv_backend or []
            total_episodes = list(range(1, total_num + 1))
            exists_episodes: set[int] = set()
            for idx, dest_path in enumerate(dest_paths):
                backend_id = backends[idx] if idx < len(backends) else "local"
                category = safe_category_name(getattr(meta_info_obj, "category", ""))
                files: list[str] = []
                for media_path in self._layout_dirs(dest_path, dir_name, category, category_flag):
                    check_path = os.path.join(media_path, season_name)
                    if self._exists(check_path, backend_id):
                        files.extend(self._get_dir_files(check_path, backend_id, RMT_MEDIAEXT))
                if not files:
                    continue
                exists_episodes |= self._episodes_from_files(files, meta_info_obj, meta_info_fn, season)
            return list(set(total_episodes).difference(exists_episodes))
