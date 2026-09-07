"""
FileIndexService - 媒体库文件索引服务
后台维护媒体库 + 同步源目录的文件索引，支持 O(1) 搜索响应。

实现：
- 启动时后台线程全量扫描构建索引
- 每 5 分钟自动重建
- 索引数据存储在 app.utils.cache_system 的内存缓存中
- 提供内存中字符串匹配搜索（遍历，万级文件毫秒级）
"""

from __future__ import annotations

import os
import threading

import log
from app.core.constants import RMT_MEDIAEXT
from app.core.settings import settings
from app.infrastructure.cache_system import get_cache_manager
from app.infrastructure.distributed_lock.lock_manager import get_lock_manager

_CACHE_NAME = "file_index"
_KEY_INDEX = "index"
_KEY_READY = "ready"
_KEY_COUNT = "count"


class FileIndexService:
    """文件索引服务"""

    def __init__(self, sync_path_repo, history_manager=None):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._cache = get_cache_manager().get_or_create(_CACHE_NAME, "memory", maxsize=10, ttl=None)
        self._sync_path_repo = sync_path_repo
        self._history_manager = history_manager

    # ---------- 生命周期 ----------

    def start(self) -> None:
        """启动后台索引线程。

        为减少对磁盘的反复扫描（避免唤醒休眠盘），默认**不自动**定时扫描，
        仅在配置 media.file_index_auto=true 时才启动周期性重建；否则由用户在
        文件管理界面手动触发 refresh()。
        """
        if not self._get_auto_index_enabled():
            log.info("[FileIndex]文件索引自动扫描已关闭（手动/按需），不启动后台线程")
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._build_index_loop, daemon=True)
        self._thread.start()
        log.info("[FileIndex]文件索引自动扫描已启动")

    def stop(self) -> None:
        """停止后台索引线程"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("[FileIndex]文件索引服务已停止")

    def refresh(self) -> None:
        """手动触发一次重建"""
        threading.Thread(target=self._rebuild_index, daemon=True).start()

    @property
    def is_ready(self) -> bool:
        return bool(self._cache.get(_KEY_READY))

    @property
    def indexed_count(self) -> int:
        return self._cache.get(_KEY_COUNT) or 0

    # ---------- 索引构建 ----------

    def _build_index_loop(self) -> None:
        """后台循环：先立即建一次，之后按配置间隔重建（默认不自动启用）。"""
        self._rebuild_index()
        interval = self._get_index_interval()
        log.info(f"[FileIndex]文件索引自动重建间隔 {interval} 秒")
        while not self._stop_event.is_set():
            self._stop_event.wait(interval)
            if not self._stop_event.is_set():
                self._rebuild_index()

    def _get_auto_index_enabled(self) -> bool:
        """是否启用文件索引自动扫描（默认关闭，避免频繁唤醒磁盘）。"""
        try:
            media = settings.get("media") or {}
            return bool(media.get("file_index_auto", False))
        except Exception:  # noqa: BLE001
            return False

    def _get_index_interval(self) -> int:
        """自动重建间隔（秒）。默认 3600 秒（1 小时），最小 600 秒。"""
        try:
            media = settings.get("media") or {}
            val = int(media.get("file_index_interval", 3600) or 3600)
            return max(val, 600)
        except Exception:  # noqa: BLE001
            return 3600

    def _rebuild_index(self) -> None:
        """全量扫描所有根目录，重建索引"""
        lock = get_lock_manager().create_lock("fileindex:rebuild", ttl_seconds=600)
        acquired = lock.acquire()
        if not acquired:
            log.info("[FileIndex]索引重建正在执行，跳过")
            return
        try:
            roots = self._get_root_paths()
            if not roots:
                log.warn("[FileIndex]未配置媒体库或同步源目录，索引为空")
                self._cache.set(_KEY_INDEX, {})
                self._cache.set(_KEY_READY, True)
                self._cache.set(_KEY_COUNT, 0)
                return

            new_index: dict[str, dict] = {}
            seen: set[str] = set()

            for root in roots:
                if not root or not os.path.isdir(root):
                    continue
                try:
                    self._scan_dir(root, new_index, seen)
                except Exception as e:
                    log.warn(f"[FileIndex]扫描目录失败 {root}: {e}")

            self._cache.set(_KEY_INDEX, new_index)
            self._cache.set(_KEY_READY, True)
            self._cache.set(_KEY_COUNT, len(new_index))
            log.info(f"[FileIndex]索引重建完成，共 {len(new_index)} 个文件，根目录: {roots}")
        finally:
            lock.release()

    def _get_root_paths(self) -> list[str]:
        """获取所有需要索引的根目录"""
        cfg = settings
        roots: list[str] = []

        # 媒体库目录
        media = cfg.get("media") or {}
        for key in ("movie_path", "tv_path", "anime_path"):
            paths = media.get(key) or []
            if isinstance(paths, str):
                paths = [paths]
            for p in paths:
                if p:
                    roots.append(os.path.normpath(p).replace("\\", "/"))

        # 同步源目录
        try:
            for conf in self._sync_path_repo.get_config_sync_paths():
                if conf:
                    src = getattr(conf, "SOURCE", None) or (
                        conf.__dict__.get("SOURCE") if hasattr(conf, "__dict__") else None
                    )
                    if src:
                        roots.append(os.path.normpath(src).replace("\\", "/"))
        except Exception as e:  # noqa: BLE001
            log.debug(f"[FileIndex]忽略异常: {e}")

        # 去重
        seen: set[str] = set()
        result = []
        for r in roots:
            if r and r not in seen:
                seen.add(r)
                result.append(r)
        return result

    def _scan_dir(self, directory: str, index: dict[str, dict], seen: set[str]) -> None:
        """递归扫描目录，只索引媒体文件 + 目录（供浏览用）"""
        try:
            entries = os.scandir(directory)
        except (OSError, PermissionError):
            return

        for entry in entries:
            if len(index) >= 50000:  # 上限 5 万文件
                return

            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except (OSError, PermissionError):
                continue

            norm_path = entry.path.replace("\\", "/")
            if norm_path in seen:
                continue
            seen.add(norm_path)

            if is_dir:
                # 目录入索引（供浏览时快速定位）
                index[norm_path] = {
                    "name": entry.name,
                    "path": norm_path,
                    "is_dir": True,
                }
                self._scan_dir(entry.path, index, seen)
            else:
                # 只索引媒体扩展名
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in RMT_MEDIAEXT:
                    item = {
                        "name": entry.name,
                        "path": norm_path,
                        "is_dir": False,
                        "ext": ext,
                    }
                    try:
                        st = entry.stat(follow_symlinks=False)
                        item["size"] = st.st_size
                        item["mtime"] = st.st_mtime
                        item["ctime"] = st.st_ctime
                    except OSError:
                        item["size"] = None
                        item["mtime"] = None
                        item["ctime"] = None
                    index[norm_path] = item

    # ---------- 搜索 ----------

    def _get_index(self) -> dict[str, dict]:
        """获取当前索引字典"""
        return self._cache.get(_KEY_INDEX) or {}

    def search(self, keyword: str, limit: int = 100) -> list[dict]:
        """关键词搜索，返回匹配的文件列表"""
        if not keyword:
            return []

        kw = keyword.lower()
        results = []
        index = self._get_index()

        for item in index.values():
            if item.get("is_dir"):
                continue
            if kw in item["name"].lower():
                results.append(dict(item))
                if len(results) >= limit:
                    break

        return results

    def search_dirs(self, keyword: str, limit: int = 50) -> list[dict]:
        """搜索目录"""
        if not keyword:
            return []

        kw = keyword.lower()
        results = []
        index = self._get_index()

        for item in index.values():
            if not item.get("is_dir"):
                continue
            if kw in item["name"].lower():
                results.append(dict(item))
                if len(results) >= limit:
                    break

        return results

    def get_dir_contents(self, path: str) -> list[dict]:
        """获取指定目录下的内容（用于浏览时的快速目录跳转）"""
        norm = (path or "").replace("\\", "/").rstrip("/")
        prefix = norm + "/"
        results = []
        index = self._get_index()

        for item in index.values():
            p = item["path"]
            if p == norm:
                continue
            if p.startswith(prefix):
                rest = p[len(prefix) :]
                if "/" not in rest:  # 直接子项
                    results.append(dict(item))

        results.sort(key=lambda x: (not x.get("is_dir", False), x["name"].lower()))
        return results

    def find_path(self, keyword: str) -> str | None:
        """搜索并返回第一个匹配文件的所在目录"""
        results = self.search(keyword, limit=1)
        if results:
            p = results[0]["path"]
            return os.path.dirname(p).replace("\\", "/")
        return None

    def find_by_name(self, name: str, limit: int = 50) -> list[dict]:
        """按文件名（精确匹配）返回所有存在该文件的条目（含路径/大小）。

        用于"媒体库一致性校验"：跨盘移动后，用原记录的文件名在全盘索引中
        查找候选新位置。索引项含 name/path/ext/size。
        """
        if not name:
            return []
        index = self._get_index()
        results = []
        for item in index.values():
            if item.get("is_dir"):
                continue
            if item.get("name") == name:
                results.append(dict(item))
                if len(results) >= limit:
                    break
        return results

    # ---------- 多版本 / 重复文件识别 ----------

    def _spec_from_filename(self, filename: str) -> str:
        """从文件名提取一个简短的规格描述（如 2160p/Remux/H265）"""
        try:
            from app.media import meta_info

            mi = meta_info(title=filename)
            parts = [
                str(getattr(mi, "resource_pix", "") or ""),
                str(getattr(mi, "resource_effect", "") or "") or str(getattr(mi, "resource_type", "") or ""),
                str(getattr(mi, "video_encode", "") or ""),
                str(getattr(mi, "audio_encode", "") or ""),
            ]
            return "/".join(p for p in parts if p and p != "None") or "未知规格"
        except Exception as e:  # noqa: BLE001
            log.debug(f"[FileIndex]规格解析失败 {filename}: {e}")
            return "未知规格"

    def list_duplicates(self, limit: int = 100) -> list[dict]:
        """列出全部存在多版本/重复文件的作品（按 tmdb_id 聚合）。

        以 TRANSFER_HISTORY 的落盘文件为基础，同一 tmdb_id 对应多个不同文件即视为多版本。
        """
        if not self._history_manager:
            return []
        try:
            groups = self._history_manager.get_multi_version_groups(limit=limit) or []
        except Exception as e:  # noqa: BLE001
            log.debug(f"[FileIndex]多版本分组查询失败: {e}")
            return []
        result = []
        for g in groups:
            tmdb_id = g.get("tmdb_id")
            result.append(
                {
                    "tmdb_id": tmdb_id,
                    "title": g.get("title"),
                    "year": g.get("year"),
                    "dir_count": g.get("dir_count"),
                    "file_count": g.get("file_count"),
                    "versions": self.get_versions(tmdb_id),
                }
            )
        return result

    def get_versions(self, tmdb_id: int) -> list[dict]:
        """列出某作品（tmdb_id）的全部版本文件，标注规格、是否存在于磁盘、硬链接兄弟。"""
        if not self._history_manager or not tmdb_id:
            return []
        try:
            infos = self._history_manager.get_transfer_info_by(tmdbid=tmdb_id) or []
        except Exception as e:  # noqa: BLE001
            log.debug(f"[FileIndex]查询转移记录失败 tmdb={tmdb_id}: {e}")
            return []
        versions = []
        for info in infos:
            dest_path = getattr(info, "DEST_PATH", "")
            dest_filename = getattr(info, "DEST_FILENAME", "")
            if not dest_path or not dest_filename:
                continue
            full = os.path.join(dest_path, dest_filename)
            exists = os.path.exists(full)
            version = {
                "source_filename": getattr(info, "SOURCE_FILENAME", ""),
                "dest_path": dest_path,
                "dest_filename": dest_filename,
                "full_path": full,
                "season_episode": getattr(info, "SEASON_EPISODE", ""),
                "date": getattr(info, "DATE", ""),
                "exists": exists,
                "spec": self._spec_from_filename(dest_filename),
                "hardlinks": self._find_hardlinks(full) if exists else [],
            }
            versions.append(version)
        # 按存在性/日期排序：存在的在前、最新在前
        versions.sort(key=lambda v: (not v["exists"], v["date"] or ""), reverse=False)
        return versions

    def _find_hardlinks(self, path: str) -> list[str]:
        """返回文件的硬链接兄弟路径列表（不含自身）"""
        try:
            from app.utils.system_utils import SystemUtils

            links = SystemUtils().find_hardlinks(file=path, fdir=os.path.dirname(path)) or []
            return [l.get("file") for l in links if l.get("file")]
        except Exception as e:  # noqa: BLE001
            log.debug(f"[FileIndex]硬链接查找失败 {path}: {e}")
            return []

    # ---------- 文件关系分析（源/媒体库一致性） ----------

    def get_file_relations(
        self,
        search: str | None = None,
        state: str | None = None,
        page: int = 1,
        page_size: int = 50,
        with_hardlinks: bool = False,
        max_pages: int = 200,
    ) -> dict:
        """分析转移记录中源文件与媒体库文件在磁盘上的存在关系。

        状态分类（基于 TRANSFERHISTORY 的 SOURCE_* / DEST_* 在磁盘的存在性）：
        - only_source: 源文件在，媒体库目标不存在（只有源、无媒体库）
        - only_dest:   媒体库目标在，源文件不存在（只有媒体库、无源）
        - both:        源与媒体库目标都在（完整硬链接链）
        - none:        两者都不存在（均已删除/丢失）
        - unknown:     记录缺少源或目标路径，无法判定

        返回 {total, items: [relation, ...]}。with_hardlinks=True 时每个文件附带硬链接兄弟路径。
        """
        search = (search or "").strip().lower()
        items = []
        for p in range(1, max_pages + 1):
            _, records = self._history_manager.get_transfer_history(search=None, page=p, rownum=500)
            if not records:
                break
            for rec in records:
                source_path = getattr(rec, "SOURCE_PATH", "") or ""
                source_filename = getattr(rec, "SOURCE_FILENAME", "") or ""
                dest_path = getattr(rec, "DEST_PATH", "") or ""
                dest_filename = getattr(rec, "DEST_FILENAME", "") or ""
                source_full = os.path.join(source_path, source_filename) if source_path and source_filename else ""
                dest_full = os.path.join(dest_path, dest_filename) if dest_path and dest_filename else ""
                if not source_full and not dest_full:
                    continue
                source_exists = bool(source_full and os.path.exists(source_full))
                dest_exists = bool(dest_full and os.path.exists(dest_full))
                if source_exists and dest_exists:
                    rel_state = "both"
                elif source_exists:
                    rel_state = "only_source"
                elif dest_exists:
                    rel_state = "only_dest"
                elif source_full or dest_full:
                    rel_state = "none"
                else:
                    rel_state = "unknown"

                # 搜索过滤
                if search:
                    haystack = (
                        f"{getattr(rec, 'TITLE', '')} {source_filename} {dest_filename}"
                    ).lower()
                    if search not in haystack:
                        continue
                if state and state != rel_state:
                    continue

                rel = {
                    "id": getattr(rec, "ID", None),
                    "tmdb_id": getattr(rec, "TMDBID", None),
                    "title": getattr(rec, "TITLE", ""),
                    "year": getattr(rec, "YEAR", ""),
                    "season_episode": getattr(rec, "SEASON_EPISODE", ""),
                    "state": rel_state,
                    "source": {"path": source_path, "filename": source_filename, "full_path": source_full, "exists": source_exists},
                    "dest": {"path": dest_path, "filename": dest_filename, "full_path": dest_full, "exists": dest_exists},
                }
                if with_hardlinks:
                    rel["source"]["hardlinks"] = self._find_hardlinks(source_full) if source_exists else []
                    rel["dest"]["hardlinks"] = self._find_hardlinks(dest_full) if dest_exists else []
                items.append(rel)
            if len(records) < 500:
                break

        total = len(items)
        start = max(0, (int(page) - 1) * int(page_size))
        return {
            "total": total,
            "state_counts": {
                "only_source": sum(1 for r in items if r["state"] == "only_source"),
                "only_dest": sum(1 for r in items if r["state"] == "only_dest"),
                "both": sum(1 for r in items if r["state"] == "both"),
                "none": sum(1 for r in items if r["state"] == "none"),
                "unknown": sum(1 for r in items if r["state"] == "unknown"),
            },
            "items": items[start : start + int(page_size)],
        }
