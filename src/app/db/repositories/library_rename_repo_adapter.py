"""媒体库批量重命名仓储适配器.

将 ORM 对象转换为普通 dict，避免业务层直接依赖 SQLAlchemy 模型。
"""

from typing import Any

from app.db.repositories.library_rename_repository import (
    LibraryRenameRepository,
    now_str,
    path_hash,
)


def _as_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class LibraryRenameRepositoryAdapter:
    """批量重命名 job/item 与元数据缓存适配器."""

    def __init__(self, repo: LibraryRenameRepository | None = None):
        self._repo = repo or LibraryRenameRepository()

    # ---------- job ----------

    def create_job(self, plan_id: str, scope: dict, rule_snapshot: dict, created_by: int | None = None) -> int:
        return self._repo.create_job(plan_id, scope, rule_snapshot, created_by)

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        return _as_dict(self._repo.get_job(job_id))

    def get_job_by_plan(self, plan_id: str) -> dict[str, Any] | None:
        return _as_dict(self._repo.get_job_by_plan(plan_id))

    def update_job(self, job_id: int, **kwargs: Any) -> None:
        self._repo.update_job(job_id, **kwargs)

    def update_job_status(self, job_id: int, status: str, **kwargs: Any) -> None:
        self._repo.update_job_status(job_id, status, **kwargs)

    def refresh_job_counters(self, job_id: int) -> None:
        self._repo.refresh_job_counters(job_id)

    def list_running_jobs(self) -> list[dict[str, Any]]:
        return [_as_dict(row) or {} for row in self._repo.list_running_jobs()]

    # ---------- item ----------

    def add_items(self, job_id: int, items: list[dict]) -> None:
        self._repo.add_items(job_id, items)

    def get_item(self, item_id: int) -> dict[str, Any] | None:
        return _as_dict(self._repo.get_item(item_id))

    def list_items(
        self, job_id: int, page: int = 1, page_size: int = 100, action: str | None = None
    ) -> tuple[int, list[dict[str, Any]]]:
        total, rows = self._repo.list_items(job_id, page, page_size, action)
        return total, [_as_dict(row) or {} for row in rows]

    def list_all_items(self, job_id: int) -> list[dict[str, Any]]:
        return [_as_dict(row) or {} for row in self._repo.list_all_items(job_id)]

    def list_running_items(self, job_id: int) -> list[dict[str, Any]]:
        return [_as_dict(row) or {} for row in self._repo.list_running_items(job_id)]

    def list_planned_items(self, job_id: int) -> list[dict[str, Any]]:
        return [_as_dict(row) or {} for row in self._repo.list_planned_items(job_id)]

    def list_done_items(self, job_id: int) -> list[dict[str, Any]]:
        return [_as_dict(row) or {} for row in self._repo.list_done_items(job_id)]

    def update_item(self, item_id: int, **kwargs: Any) -> None:
        self._repo.update_item(item_id, **kwargs)

    def update_items_by_status(self, job_id: int, statuses: tuple[str, ...], **kwargs: Any) -> None:
        self._repo.update_item_status_by_job(job_id, statuses, **kwargs)

    # ---------- history ----------

    def get_history_by_dest(self, dest_path: str, dest_filename: str) -> list[dict[str, Any]]:
        return [row.as_dict() for row in self._repo.get_history_by_dest(dest_path, dest_filename)]

    def update_history_dest(
        self,
        old_dir: str,
        old_filename: str,
        new_dir: str,
        new_filename: str,
        category: str | None = None,
    ) -> int:
        return self._repo.update_history_dest_by_path(old_dir, old_filename, new_dir, new_filename, category)

    # ---------- metadata cache ----------

    def get_metadata(self, backend_id: str, path: str) -> dict[str, Any] | None:
        return _as_dict(self._repo.get_metadata(backend_id, path))

    def upsert_metadata(
        self,
        backend_id: str,
        path: str,
        data: dict[str, Any],
        *,
        is_manual: bool = False,
        user_id: int | None = None,
    ) -> None:
        self._repo.upsert_metadata(backend_id, path, data, is_manual=is_manual, user_id=user_id)

    def update_metadata_path(
        self,
        backend_id: str,
        old_path: str,
        new_path: str,
        *,
        file_size: int | None = None,
        file_mtime: float | None = None,
    ) -> None:
        self._repo.update_metadata_path(backend_id, old_path, new_path, file_size=file_size, file_mtime=file_mtime)

    @staticmethod
    def now_str() -> str:
        return now_str()

    @staticmethod
    def path_hash(path: str) -> str:
        return path_hash(path)
