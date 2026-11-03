"""转移记录的保留策略：旧版本怎么处理。

真实使用里有三种互斥诉求，不能用一个默认行为覆盖：

- ``keep``（默认）  源文件从下载器消失时保留媒体库文件；新版本入库时与旧版并存。
  qb 里清理种子不应该连累媒体库，所以默认永不自动删除。
- ``sync_delete``  源文件消失时同步删除媒体库文件，让「删源」真正等于「删库」。
- ``replace``      新版本入库成功后，删除同作品同季同集的旧版本（洗版）。
  源文件消失时仍然保留媒体库，因为旧版可能还要留着看。

策略存在 ``TRANSFER_HISTORY.RETENTION_POLICY``，按记录控制 —— 用户对不同作品
有不同打算（这部想更新、那部想留着），全局开关无法表达。
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

import log
from app.db.repositories.transfer_repository import TransferRepository
from app.services.transfer.media_file_deletion_service import MediaFileDeletionService
from app.utils import PathUtils


class RetentionPolicy:
    """可用的保留策略取值。"""

    KEEP = "keep"
    SYNC_DELETE = "sync_delete"
    REPLACE = "replace"

    ALL = (KEEP, SYNC_DELETE, REPLACE)
    DEFAULT = KEEP

    @classmethod
    def normalize(cls, value: Any) -> str:
        text = str(value or "").strip().lower()
        return text if text in cls.ALL else cls.DEFAULT


class RetentionService:
    """按记录策略清理媒体库文件（源消失、版本替换）。"""

    def __init__(
        self,
        history: TransferRepository | None = None,
        file_service: MediaFileDeletionService | None = None,
        path_resolver: Any = None,
    ):
        self._history = history or TransferRepository()
        self._path_resolver = path_resolver
        self._file_service = file_service

    # ---------- 策略读写 ----------

    def set_policy(self, logids: list[int], policy: str) -> int:
        """设置若干记录的保留策略，返回生效条数."""
        normalized = RetentionPolicy.normalize(policy)
        updated = 0
        for logid in logids:
            try:
                if self._history.update_retention_policy(int(logid), normalized):
                    updated += 1
            except Exception as e:  # noqa: BLE001
                log.warn(f"[Retention]设置策略失败 ID={logid}: {e}")
        return updated

    def get_policy(self, record) -> str:
        return RetentionPolicy.normalize(getattr(record, "RETENTION_POLICY", None))

    # ---------- 源消失 ----------

    def apply_source_missing(self, records: list, exists: Callable[[Any], bool] | None = None) -> dict:
        """检测源文件是否还在，并按策略处理。

        只有 ``sync_delete`` 会动媒体库；``keep`` 与 ``replace`` 一律只标记状态。
        返回 {marked, deleted, failed} 统计，便于日志与接口回显。
        """
        check = exists or self._source_exists
        stats = {"marked": 0, "deleted": 0, "failed": 0}
        for record in records or []:
            if check(record):
                continue
            state = str(getattr(record, "SOURCE_STATE", "") or "")
            if state == "missing":
                continue
            try:
                self._history.update_transfer_file_state(
                    int(record.ID),
                    source_state="missing",
                    source_deleted_at=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                )
            except Exception as e:  # noqa: BLE001
                log.debug(f"[Retention]标记源缺失失败 ID={getattr(record, 'ID', '?')}: {e}")
                continue
            stats["marked"] += 1
            if self.get_policy(record) != RetentionPolicy.SYNC_DELETE:
                continue
            if self._delete_dest(record):
                stats["deleted"] += 1
            else:
                stats["failed"] += 1
        return stats

    def _source_exists(self, record) -> bool:
        path = PathUtils.join_path(
            str(getattr(record, "SOURCE_PATH", "") or ""), str(getattr(record, "SOURCE_FILENAME", "") or "")
        )
        return bool(path) and os.path.exists(path)

    # ---------- 版本替换 ----------

    def replace_older_versions(self, new_record) -> int:
        """新版本入库后，按 replace 策略清理同集旧版本，返回清理条数.

        只处理与 ``new_record`` 同一 identity（或同一 TMDBID）、同一季同一集的其它记录。
        新记录自身、以及策略非 ``replace`` 的旧记录都不动 —— 用户没要求换版就绝不删。
        """
        if new_record is None:
            return 0
        try:
            siblings = self._history.get_same_episode_records(new_record)
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Retention]查询同集记录失败: {e}")
            return 0
        removed = 0
        for old in siblings or []:
            if getattr(old, "ID", None) == getattr(new_record, "ID", None):
                continue
            if self.get_policy(old) != RetentionPolicy.REPLACE:
                continue
            if not self._delete_dest(old):
                continue
            try:
                self._history.delete_transfer_logs([int(old.ID)])
            except Exception as e:  # noqa: BLE001
                log.warn(f"[Retention]删除旧版记录失败 ID={getattr(old, 'ID', '?')}: {e}")
                continue
            removed += 1
            log.info(f"[Retention]已替换旧版本 ID={getattr(old, 'ID', '?')} → 新版 ID={getattr(new_record, 'ID', '?')}")
        return removed

    # ---------- 内部 ----------

    def _delete_dest(self, record) -> bool:
        """删除记录对应的媒体库文件；成功（或已不存在）返回 True."""
        dest_path = str(getattr(record, "DEST_PATH", "") or "")
        dest_filename = str(getattr(record, "DEST_FILENAME", "") or "")
        if not dest_path or not dest_filename:
            return False
        backend_id = str(getattr(record, "DST_BACKEND", None) or "local")
        try:
            service = self._file_service or self._build_file_service()
            service.delete_media_file(dest_path, dest_filename, backend_id=backend_id)
        except Exception as e:  # noqa: BLE001
            # 文件本就不在也视为达成目标，不必反复重试
            if type(e).__name__ == "ResourceNotFoundError":
                self._mark_dest_deleted(record)
                return True
            log.warn(f"[Retention]删除媒体库文件失败 ID={getattr(record, 'ID', '?')}: {e}")
            return False
        self._mark_dest_deleted(record)
        log.info(f"[Retention]已删除媒体库文件 ID={getattr(record, 'ID', '?')}: {dest_path}/{dest_filename}")
        return True

    def _mark_dest_deleted(self, record) -> None:
        try:
            self._history.update_transfer_file_state(int(record.ID), dest_state="deleted")
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Retention]回写 DEST_STATE 失败: {e}")

    def _build_file_service(self) -> MediaFileDeletionService:
        # 媒体库都是本地后端时 resolve_backend_by_id 不依赖 path_resolver，
        # 因此这里允许为空；只有配了远程后端才需要注入。
        return MediaFileDeletionService(self._path_resolver)


class RetentionSweep:
    """周期对账用的保留策略入口：只处理用户显式表态过的记录。

    安全性来自「默认为空」：没有任何记录的 RETENTION_POLICY 被设置时，
    sweep 只做状态标记（写 SOURCE_STATE=missing），不删任何文件。
    """

    def __init__(self, path_resolver: Any = None, history: TransferRepository | None = None):
        self._history = history or TransferRepository()
        self._service = RetentionService(history=self._history, path_resolver=path_resolver)

    def sweep(self, limit: int = 2000) -> dict:
        stats = {"scanned": 0, "marked": 0, "deleted": 0, "replaced": 0, "failed": 0}
        records = self._load_candidates(limit)
        stats["scanned"] = len(records)

        # 1. 源缺失检测（sync_delete 才会删库）
        try:
            missing_stats = self._service.apply_source_missing(records)
            stats["marked"] = missing_stats["marked"]
            stats["deleted"] = missing_stats["deleted"]
            stats["failed"] = missing_stats["failed"]
        except Exception as e:  # noqa: BLE001
            log.warn(f"[Retention]源缺失检测失败: {e}")

        # 2. 洗版：policy=replace 的旧记录，若同集已有更新的记录则清理
        try:
            stats["replaced"] = self._replace_superseded()
        except Exception as e:  # noqa: BLE001
            log.warn(f"[Retention]版本替换失败: {e}")
        return stats

    def _load_candidates(self, limit: int) -> list:
        """只取需要关注的记录：有源路径的。数量可控，避免每轮全表扫。"""
        try:
            return self._history.get_records_for_retention(limit=limit)
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Retention]读取候选记录失败: {e}")
            return []

    def _replace_superseded(self) -> int:
        """policy=replace 且存在更新的同集记录 → 删除该旧记录及其文件."""
        candidates = self._history.get_replace_candidates()
        removed = 0
        for old in candidates or []:
            if not self._service._delete_dest(old):  # noqa: SLF001 - 同类协作
                continue
            try:
                self._history.delete_transfer_logs([int(old.ID)])
            except Exception as e:  # noqa: BLE001
                log.warn(f"[Retention]删除旧版记录失败 ID={getattr(old, 'ID', '?')}: {e}")
                continue
            removed += 1
            log.info(f"[Retention]旧版本已被替代并清理 ID={getattr(old, 'ID', '?')}")
        return removed
