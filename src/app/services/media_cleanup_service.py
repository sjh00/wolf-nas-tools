"""MediaCleanupService - 按文件锚点清理媒体库/做种/记录/下载器任务.

用户压制替换场景：以用户选中的媒体库文件（或其任何硬链接兄弟）为锚点，
清理该文件及其硬链接链上所有关联内容（媒体库目标文件 + 做种源文件 + 转移/下载记录 + 下载器任务），
但**保留**同一作品（tmdb_id）下其它版本文件（那些不是同一 inode 硬链接的文件）。

与 `TransferCleanupService.delete_history`（按 logid + flag 删一条记录）配合，
这里负责"先定位硬链接链 → 收集待删记录 → 调 delete_history + 删除下载器任务"的编排。
"""

import os

import log
from app.core.settings import settings
from app.db.repositories.download_repo_adapter import DownloadHistoryRepositoryAdapter
from app.events import Event
from app.events.bus import EventBus
from app.events.constants import LIBRARY_FILE_DELETED, MEDIA_SOURCE_DELETED
from app.events.payloads import LibraryFileDeletedPayload, MediaSourceDeletedPayload
from app.utils.system_utils import SystemUtils


class MediaCleanupService:
    """按文件锚点清理其硬链接链上的媒体库文件、做种文件、转移/下载记录及下载器任务。"""

    def __init__(
        self,
        cleanup_service,
        history_manager,
        downloader_core,
        download_repo: DownloadHistoryRepositoryAdapter | None = None,
        event_bus: EventBus | None = None,
    ):
        self._cleanup = cleanup_service
        self._history = history_manager
        self._downloader_core = downloader_core
        self._download_repo = download_repo or DownloadHistoryRepositoryAdapter()
        self._event_bus = event_bus

    # ---------- 对外入口 ----------

    def cleanup_file_chain(self, file_path: str, delete_downloader: bool = True, source_policy: str = "remove") -> dict:
        """以 file_path 为锚点清理其硬链接链。

        source_policy 控制"做种源文件"的处理方式：
        - "remove"（默认）：全部删干净 —— 删媒体库目标 + 做种源文件 + 转移/下载记录 + 下载器任务。
        - "keep"（不动源）：只删媒体库目标硬链接，保留做种源文件、转移记录、下载器任务，
          结果在文件管理呈现"只有源、无媒体库"状态，供用户后续自行处理。

        返回统计信息：{deleted_files, deleted_transfer_logs, deleted_torrents, source_policy}。
        """
        if not file_path or not os.path.exists(file_path):
            raise ValueError(f"文件不存在：{file_path}")

        # 1. 定位硬链接链（媒体库目标 + 做种源文件，共享同一 inode）
        chain_paths = self._find_chain_paths(file_path)
        log.info(f"[Cleanup]硬链接链：{len(chain_paths)} 个文件 -> {chain_paths}")

        # 2a. "不动源"：只删媒体库目标硬链接，保留源文件/记录/任务
        if source_policy == "keep":
            deleted_files = self._delete_dest_files_only(chain_paths)
            deleted_torrents = []
            deleted_transfer_logs = 0
            return {
                "anchor": file_path,
                "chain_files": chain_paths,
                "deleted_files": deleted_files,
                "deleted_transfer_logs": 0,
                "deleted_torrents": [],
                "source_policy": source_policy,
            }

        # 2b. "全部删干净"（默认）
        deleted_files = []
        deleted_transfer_logs = self._delete_transfer_records(chain_paths, deleted_files)

        # 3. 删除下载器任务（避免做种文件已删后下载器报红），并删下载记录
        deleted_torrents = []
        if delete_downloader:
            deleted_torrents = self._delete_downloader_tasks(chain_paths)

        return {
            "anchor": file_path,
            "chain_files": chain_paths,
            "deleted_files": deleted_files,
            "deleted_transfer_logs": deleted_transfer_logs,
            "deleted_torrents": deleted_torrents,
            "source_policy": source_policy,
        }

    # ---------- "不动源"：仅删媒体库目标硬链接 ----------

    def _delete_dest_files_only(self, chain_paths: list[str]) -> list[str]:
        """仅删除媒体库目标（DEST）硬链接，保留做种源文件与转移记录。

        结果：记录仍在（源在、媒体库缺）→ 文件管理呈现"只有源无媒体库"。
        """
        deleted = []
        try:
            logs = self._history.get_transfer_logs_by_paths(chain_paths) or []
        except Exception as e:  # noqa: BLE001
            log.error(f"[Cleanup]‘不动源’查询转移记录失败: {e}")
            logs = []

        # 收集待删的媒体库目标路径（DEST_PATH/DEST_FILENAME）
        dest_paths = []
        for t in logs:
            dp = getattr(t, "DEST_PATH", "") or ""
            df = getattr(t, "DEST_FILENAME", "") or ""
            if dp and df:
                dest_paths.append(os.path.join(dp, df))

        if not dest_paths:
            # 无法从记录定位 DEST 时，删链上"不在媒体库源目录"的文件兜底
            for p in chain_paths:
                if os.path.exists(p):
                    dest_paths.append(p)

        for dest in dest_paths:
            if not dest or not os.path.exists(dest):
                continue
            try:
                # 复用删媒体文件（保留源，只删目标）
                self._cleanup.delete_media_file(
                    os.path.dirname(dest), os.path.basename(dest)
                )
                deleted.append(dest)
                log.info(f"[Cleanup]已删除媒体库目标（保留源）：{dest}")
                # 发布媒体库文件删除事件，供媒体服务器/下游感知
                if self._event_bus:
                    try:
                        self._event_bus.publish(
                            Event(
                                event_type=LIBRARY_FILE_DELETED,
                                payload=LibraryFileDeletedPayload(
                                    media_info={}, path=os.path.dirname(dest), filename=os.path.basename(dest)
                                ),
                            )
                        )
                    except Exception as e:  # noqa: BLE001
                        log.debug(f"[Cleanup]事件发布失败 {dest}: {e}")
            except Exception as e:  # noqa: BLE001
                log.warn(f"[Cleanup]删除媒体库目标失败 {dest}: {e}")

        return deleted

    # ---------- 硬链接链定位 ----------

    def _find_chain_paths(self, file_path: str) -> list[str]:
        """返回 file_path 及其所有硬链接兄弟（不含自身）的绝对路径列表。"""
        result = [os.path.normpath(file_path)]
        try:
            links = SystemUtils().find_hardlinks(file=file_path, fdir=os.path.dirname(file_path)) or []
            for link in links:
                p = link.get("file")
                if p and os.path.normpath(p) not in result:
                    result.append(os.path.normpath(p))
        except Exception as e:  # noqa: BLE001
            log.warn(f"[Cleanup]查找硬链接失败 {file_path}: {e}")
        return result

    # ---------- 转移记录删除 ----------

    def _delete_transfer_records(self, chain_paths: list[str], deleted_files: list[str]) -> int:
        """删除涉及链上文件的全部转移记录（媒体库目标 + 做种源 + 记录）。

        复用 TransferCleanupService.delete_history(flag='del_all') 删除文件与记录，
        并发布删除事件供媒体服务器/下游感知。
        """
        try:
            logs = self._history.get_transfer_logs_by_paths(chain_paths) or []
        except Exception as e:  # noqa: BLE001
            log.error(f"[Cleanup]查询转移记录失败: {e}")
            return 0

        logids = [getattr(t, "ID", None) for t in logs if getattr(t, "ID", None)]
        if not logids:
            return 0

        # 先手动收集将删除的文件（防 delete_history 内部异常导致信息丢失）
        for t in logs:
            src = os.path.join(getattr(t, "SOURCE_PATH", "") or "", getattr(t, "SOURCE_FILENAME", "") or "")
            dst = os.path.join(getattr(t, "DEST_PATH", "") or "", getattr(t, "DEST_FILENAME", "") or "")
            for p in (dst, src):
                if p and os.path.exists(p) and p not in deleted_files:
                    deleted_files.append(p)

        try:
            self._cleanup.delete_history(logids, flag="del_all")
        except Exception as e:  # noqa: BLE001
            log.error(f"[Cleanup]删除转移记录/文件失败: {e}")

        # 发布删除事件（供媒体服务器同步、前端感知）
        if self._event_bus:
            for p in deleted_files:
                try:
                    if self._is_library_path(p):
                        self._event_bus.publish(
                            Event(
                                event_type=LIBRARY_FILE_DELETED,
                                payload=LibraryFileDeletedPayload(
                                    media_info={}, path=os.path.dirname(p), filename=os.path.basename(p)
                                ),
                            )
                        )
                    else:
                        self._event_bus.publish(
                            Event(
                                event_type=MEDIA_SOURCE_DELETED,
                                payload=MediaSourceDeletedPayload(
                                    media_info={}, path=os.path.dirname(p), filename=os.path.basename(p)
                                ),
                            )
                        )
                except Exception as e:  # noqa: BLE001
                    log.debug(f"[Cleanup]删除事件发布失败 {p}: {e}")

        return len(logids)

    # ---------- 下载器任务删除 ----------

    def _delete_downloader_tasks(self, chain_paths: list[str]) -> list[dict]:
        """删除链上文件对应的下载器任务（避免文件已删后下载器报红），并清下载记录。"""
        deleted = []
        # 收集 (downloader, download_id) 去重
        tasks: dict[str, set[str]] = {}
        record_ids: list[int] = []
        try:
            for p in chain_paths:
                recs = self._download_repo.get_download_history_list_by_path(p) or []
                for rec in recs:
                    downloader = getattr(rec, "DOWNLOADER", "") or ""
                    download_id = getattr(rec, "DOWNLOAD_ID", "") or ""
                    rid = getattr(rec, "ID", None)
                    if rid:
                        record_ids.append(int(rid))
                    if downloader and download_id:
                        tasks.setdefault(downloader, set()).add(download_id)
        except Exception as e:  # noqa: BLE001
            log.error(f"[Cleanup]查询下载记录失败: {e}")
            return deleted

        for downloader, ids in tasks.items():
            try:
                # delete_file=True 连带删除已下载的媒体文件
                self._downloader_core.delete_torrents(
                    downloader_id=downloader, ids=list(ids), delete_file=True
                )
                deleted.append({"downloader": downloader, "ids": list(ids)})
                log.info(f"[Cleanup]已删除下载器 {downloader} 的任务：{list(ids)}")
            except Exception as e:  # noqa: BLE001
                log.error(f"[Cleanup]删除下载器 {downloader} 任务失败: {e}")

        # 清理下载记录（按 ID 删除，仅删链上文件对应的，保留同作品其它版本记录）
        if record_ids:
            try:
                self._download_repo.delete_by_ids(record_ids)
            except Exception as e:  # noqa: BLE001
                log.debug(f"[Cleanup]删除下载记录失败: {e}")
        return deleted

    def _is_library_path(self, path: str) -> bool:
        """判断路径是否位于媒体库目录（用于区分事件类型）。"""
        try:
            media = settings.get("media") or {}
            norm = os.path.normpath(path)
            for key in ("movie_path", "tv_path", "anime_path"):
                paths = media.get(key) or []
                if isinstance(paths, str):
                    paths = [paths]
                for lib in paths:
                    if lib and (norm == os.path.normpath(lib) or norm.startswith(os.path.normpath(lib) + os.sep)):
                        return True
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Cleanup]判断媒体库路径失败 {path}: {e}")
        return False
