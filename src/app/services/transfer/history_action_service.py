"""识别历史动作服务：记录删除、关联文件删除与文件状态检测."""

import os
import time
from collections.abc import Callable

from app.core.exceptions import ValidationError
from app.services.transfer.media_file_deletion_service import MediaFileDeletionService


class HistoryActionService:
    """把记录生命周期与文件生命周期拆成独立动作."""

    def __init__(
        self,
        history_manager,
        file_service: MediaFileDeletionService,
        delete_history: Callable[[list[int], str | None], None],
    ):
        self._history = history_manager
        self._files = file_service
        self._delete_history = delete_history

    def delete_records(self, logids: list[int]) -> list[dict]:
        """只删除识别记录与黑名单，不触碰任何物理文件."""
        records = self._load_records(logids)
        found = {int(record.ID) for record in records}
        if records:
            self._history.delete_transfer_logs([record.ID for record in records])
            for record in records:
                self._history.delete_transfer_blacklist(
                    os.path.join(str(record.SOURCE_PATH or ""), str(record.SOURCE_FILENAME or ""))
                )
        return [
            {
                "id": int(logid),
                "status": "deleted" if int(logid) in found else "skipped",
                "message": "" if int(logid) in found else "记录不存在",
            }
            for logid in logids
        ]

    def delete_record_files(self, logids: list[int], targets: list[str]) -> list[dict]:
        """按目标删除记录关联文件，记录本身始终保留."""
        valid_targets = list(dict.fromkeys(target for target in targets if target in ("source", "library")))
        if not valid_targets:
            raise ValidationError("未指定要删除的文件目标")

        results: list[dict] = []
        records = {int(record.ID): record for record in self._load_records(logids)}
        for logid in logids:
            record = records.get(int(logid))
            if not record:
                results.append({"id": int(logid), "target": None, "status": "skipped", "message": "记录不存在"})
                continue

            deletable: list[str] = []
            for target in valid_targets:
                if not self._target_exists(record, target):
                    state = "deleted" if self._target_deleted_at(record, target) else "missing"
                    self.persist_file_state(record, target, state)
                    results.append(
                        {
                            "id": int(logid),
                            "target": target,
                            "status": "skipped",
                            "state": state,
                            "message": "文件不存在",
                        }
                    )
                    continue
                deletable.append(target)

            if not deletable:
                continue

            flag = "del_all" if len(deletable) == 2 else ("del_source" if deletable[0] == "source" else "del_dest")
            self._delete_history([logid], flag)

            for target in deletable:
                if self._target_exists(record, target):
                    results.append(
                        {
                            "id": int(logid),
                            "target": target,
                            "status": "failed",
                            "state": self._target_state(record, target),
                            "message": "文件删除失败，请检查存储后端",
                        }
                    )
                    continue
                deleted_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                self.persist_file_state(record, target, "deleted", deleted_at)
                results.append(
                    {
                        "id": int(logid),
                        "target": target,
                        "status": "deleted",
                        "state": "deleted",
                        "message": "",
                    }
                )
        return results

    def check_record_files(self, logids: list[int], targets: list[str] | None = None) -> list[dict]:
        """检测记录关联文件是否存在，并回写状态."""
        valid_targets = list(
            dict.fromkeys(target for target in (targets or ["source", "library"]) if target in ("source", "library"))
        )
        results: list[dict] = []
        records = {int(record.ID): record for record in self._load_records(logids)}
        for logid in logids:
            record = records.get(int(logid))
            if not record:
                results.append({"id": int(logid), "target": None, "state": "unknown", "message": "记录不存在"})
                continue
            for target in valid_targets:
                if not self._target_has_path(record, target):
                    state = "unknown"
                else:
                    state = "present" if self._target_exists(record, target) else "missing"
                    if state == "missing" and self._target_deleted_at(record, target):
                        state = "deleted"
                self.persist_file_state(record, target, state)
                results.append({"id": int(logid), "target": target, "state": state, "message": ""})
            if valid_targets:
                checked_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                self._history.update_transfer_file_state(int(record.ID), files_checked_at=checked_at)
                record.FILES_CHECKED_AT = checked_at
                record.files_checked_at = checked_at
        return results

    def _load_records(self, logids: list[int]) -> list:
        records = []
        for logid in logids:
            record = self._history.get_transfer_info_by_id(logid)
            if record:
                records.append(record)
        return records

    @staticmethod
    def _target_has_path(record, target: str) -> bool:
        if target == "source":
            return bool(getattr(record, "SOURCE_PATH", "") and getattr(record, "SOURCE_FILENAME", ""))
        return bool(getattr(record, "DEST_PATH", ""))

    @staticmethod
    def _target_deleted_at(record, target: str) -> str | None:
        if target == "source":
            return getattr(record, "SOURCE_DELETED_AT", None)
        return getattr(record, "DEST_DELETED_AT", None)

    @staticmethod
    def _target_state(record, target: str) -> str:
        state = getattr(record, "SOURCE_STATE" if target == "source" else "DEST_STATE", None)
        return state or "unknown"

    def _target_exists(self, record, target: str) -> bool:
        if not self._target_has_path(record, target):
            return False
        if target == "source":
            return os.path.exists(os.path.join(str(record.SOURCE_PATH), str(record.SOURCE_FILENAME)))
        dest_path = str(getattr(record, "DEST_PATH", "") or "")
        dest_filename = str(getattr(record, "DEST_FILENAME", "") or "")
        backend_id = str(getattr(record, "DST_BACKEND", None) or "local")
        backend = self._files.resolve_backend_by_id(backend_id)
        if not backend:
            return False
        path = os.path.join(dest_path, dest_filename) if dest_filename else dest_path
        try:
            return bool(backend.exists(path))
        except Exception:
            return False

    def persist_file_state(self, record, target: str, state: str, deleted_at: str | None = None) -> None:
        clear_deleted_at = state == "present"
        if target == "source":
            self._history.update_transfer_file_state(
                int(record.ID),
                source_state=state,
                source_deleted_at="" if clear_deleted_at else deleted_at,
            )
            record.SOURCE_STATE = state
            record.SOURCE_DELETED_AT = None if clear_deleted_at else (deleted_at or record.SOURCE_DELETED_AT)
            return
        self._history.update_transfer_file_state(
            int(record.ID),
            dest_state=state,
            dest_deleted_at="" if clear_deleted_at else deleted_at,
        )
        record.DEST_STATE = state
        record.DEST_DELETED_AT = None if clear_deleted_at else (deleted_at or record.DEST_DELETED_AT)
