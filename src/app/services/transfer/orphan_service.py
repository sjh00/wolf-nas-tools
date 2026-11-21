"""转移遗漏对账。

背景：同步/转移用 ``TRANSFER_BLACKLIST`` 记录「已处理」，命中即静默跳过
（不打日志、不写记录）。这张表只有 PATH，没有时间、没有结果、没有界面，
一旦某个文件/目录在「其实没成功」或「目标已存在但没写记录」的情况下被打上标记，
它就永久消失在流程里 —— 既不在识别历史，也不在未识别列表，界面上完全看不到。

本服务做两件事：

1. ``audit()``：找出这些「无记录却被跳过」的条目，并列出没有被任何同步源覆盖的
   btstore 目录（那类目录里的文件根本没进入流程）。
2. ``purge_stale(paths)``：删除这些没有成功证据的黑名单标记，让文件重新被扫描。

删除标记是安全的：转移前会检查目标是否已存在，已在库里的文件只会被跳过，
不会重复占空间。
"""

from __future__ import annotations

import os

import log
from app.db.repositories.sync_repo_adapter import SyncPathRepositoryAdapter
from app.db.repositories.transfer_repo_adapter import (
    TransferBlacklistRepositoryAdapter,
    TransferHistoryRepositoryAdapter,
)
from app.services.media_config_service import MediaConfigService

# btstore 下不参与媒体处理的一级目录（回收站、说明等）
_IGNORE_BUCKETS = {".Trash-1000", "@eaDir", "#recycle"}

# 判定「已入库」用的媒体扩展名（与转移链路一致的主要视频容器）
_MEDIA_EXT = {".mkv", ".mp4", ".ts", ".avi", ".m2ts", ".iso", ".rmvb", ".wmv", ".flv", ".mov"}

# 原盘（BDMV）内部文件：整个目录由目录级转移统一处理，逐个文件报出来只是噪声
_DISC_PATH_MARKERS = ("/BDMV/", "/CERTIFICATE/")


class TransferOrphanService:
    """识别「被静默跳过」的源文件/目录。"""

    def __init__(
        self,
        sync_path_repo: SyncPathRepositoryAdapter | None = None,
        blacklist_repo: TransferBlacklistRepositoryAdapter | None = None,
    ):
        self._sync_path_repo = sync_path_repo or SyncPathRepositoryAdapter()
        self._blacklist_repo = blacklist_repo or TransferBlacklistRepositoryAdapter()

    # ---------- 同步源覆盖情况 ----------

    def _sync_sources(self) -> list[str]:
        sources: list[str] = []
        for entity in self._sync_path_repo.get_all() or []:
            source = str(getattr(entity, "source", "") or "").rstrip("/")
            if source and getattr(entity, "enabled", True):
                sources.append(source)
        return sources

    def uncovered_buckets(self) -> list[dict]:
        """列出存在于磁盘、但没有被任何同步源覆盖的 btstore 一级目录。

        这类目录里的文件永远不会进入识别/转移流程，且不会出现在任何列表里。
        """
        sources = self._sync_sources()
        if not sources:
            return []
        # 从同步源里推出 btstore 根：/media/x/btstore/tv → /media/x/btstore
        roots: set[str] = set()
        for source in sources:
            idx = source.find("/btstore/")
            if idx > 0:
                roots.add(source[:idx] + "/btstore")
        out: list[dict] = []
        for root in sorted(roots):
            if not os.path.isdir(root):
                continue
            covered = {os.path.basename(s) for s in sources if s.startswith(root + "/")}
            for name in sorted(os.listdir(root)):
                full = os.path.join(root, name)
                if not os.path.isdir(full) or name in _IGNORE_BUCKETS or name in covered:
                    continue
                files = 0
                size = 0
                for dirpath, _d, fnames in os.walk(full):
                    for f in fnames:
                        files += 1
                        try:
                            size += os.path.getsize(os.path.join(dirpath, f))
                        except OSError:
                            pass
                if files:
                    out.append({"path": full, "bucket": name, "files": files, "size": size})
        return out

    # ---------- 黑名单里没有成功证据的条目 ----------

    def stale_blacklist(self, limit: int = 500) -> list[dict]:
        """黑名单中「既没有转移记录、媒体库里也没有对应文件」的条目。

        判定分两步，避免把「已成功入库、只是历史记录没迁移过来」的条目误判：

        1. 有转移记录 → 正常，跳过；
        2. 无转移记录时再看媒体库：源文件的 inode 若能在媒体库找到（项目用硬链接
           入库），说明文件确实已在库里，只是缺少记录，不算遗漏。

        两步都不成立，才是「被打上跳过标记、却从没真正入库」的条目——这些文件
        既不在识别历史、也不在未识别列表，只能在磁盘上找到。
        """
        history_repo = TransferHistoryRepositoryAdapter()
        sources = self._sync_sources()
        lib_inodes: set[tuple[int, int]] | None = None
        out: list[dict] = []
        for path in self._blacklist_repo.get_all_paths() or []:
            if len(out) >= limit:
                break
            norm = str(path or "").rstrip("/")
            if not norm:
                continue
            # 原盘内部文件由目录级转移统一处理，单列只会淹没真正的问题
            if any(marker in norm + "/" for marker in _DISC_PATH_MARKERS):
                continue
            # 只关心同步源覆盖范围内的路径
            if sources and not any(norm == s or norm.startswith(s + "/") for s in sources):
                continue
            try:
                if history_repo.get_by_source(norm) is not None:
                    continue
            except Exception as e:  # noqa: BLE001
                log.debug(f"[Orphan]查询转移记录失败 {norm}: {e}")
                continue
            if lib_inodes is None:
                lib_inodes = self._library_inodes()
            is_dir = os.path.isdir(norm)
            if is_dir:
                if self._dir_in_library(norm, lib_inodes):
                    continue
                exists = True
            else:
                exists = os.path.exists(norm)
                if exists and self._file_in_library(norm, lib_inodes):
                    continue
            out.append({"path": norm, "is_dir": is_dir, "source_exists": exists})
        return out

    # ---------- 媒体库存在性 ----------

    @staticmethod
    def _library_roots() -> list[str]:
        try:
            cfg = MediaConfigService().get_config()
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Orphan]读取媒体库配置失败: {e}")
            return []
        roots: list[str] = []
        for key in ("movie_path", "tv_path", "anime_path"):
            for p in cfg.get(key) or []:
                if p and p not in roots:
                    roots.append(str(p))
        return roots

    def _library_inodes(self) -> set[tuple[int, int]]:
        """媒体库全部媒体文件的 (dev, inode)，用于判断「是否已入库」。"""
        inodes: set[tuple[int, int]] = set()
        for root in self._library_roots():
            if not os.path.isdir(root):
                continue
            for dirpath, _dirs, files in os.walk(root):
                for name in files:
                    if os.path.splitext(name)[1].lower() not in _MEDIA_EXT:
                        continue
                    try:
                        st = os.stat(os.path.join(dirpath, name))
                    except OSError:
                        continue
                    inodes.add((st.st_dev, st.st_ino))
        return inodes

    @staticmethod
    def _file_in_library(path: str, lib_inodes: set[tuple[int, int]]) -> bool:
        try:
            st = os.stat(path)
        except OSError:
            return False
        return (st.st_dev, st.st_ino) in lib_inodes

    @staticmethod
    def _dir_in_library(directory: str, lib_inodes: set[tuple[int, int]], probe: int = 5) -> bool:
        """目录里是否有媒体文件已在库（有则说明这个目录确实入过库）。"""
        checked = 0
        for dirpath, _dirs, files in os.walk(directory):
            for name in files:
                if os.path.splitext(name)[1].lower() not in _MEDIA_EXT:
                    continue
                checked += 1
                try:
                    st = os.stat(os.path.join(dirpath, name))
                except OSError:
                    continue
                if (st.st_dev, st.st_ino) in lib_inodes:
                    return True
                if checked >= probe:
                    return False
        return False

    def purge_stale(self, paths: list[str]) -> int:
        """删除指定的黑名单标记，返回删除条数。"""
        removed = 0
        for path in paths:
            try:
                self._blacklist_repo.delete(path)
                removed += 1
            except Exception as e:  # noqa: BLE001
                log.warn(f"[Orphan]删除黑名单失败 {path}: {e}")
        if removed:
            log.info(f"[Orphan]已解除 {removed} 条无成功记录的跳过标记，相关文件将重新进入识别/转移")
        return removed

    def audit(self, limit: int = 500) -> dict:
        """一次性对账结果：未被覆盖的目录 + 无成功记录的跳过条目。"""
        stale = self.stale_blacklist(limit=limit)
        uncovered = self.uncovered_buckets()
        return {
            "uncovered_buckets": uncovered,
            "stale_blacklist": stale,
            "stale_count": len(stale),
            "truncated": len(stale) >= limit,
        }
