"""媒体库路由领域实体。"""

from dataclasses import dataclass


@dataclass
class MediaLibraryRouteEntity:
    id: int = 0
    content_profile: str = ""
    target_path: str = ""
    server_id: int = 0
    backend_id: str = "local"
    library_id: str | None = None
    enabled: bool = True
    note: str = ""

    @classmethod
    def from_orm(cls, row) -> "MediaLibraryRouteEntity":
        return cls(
            id=row.ID,
            content_profile=row.CONTENT_PROFILE or "",
            target_path=row.TARGET_PATH or "",
            server_id=row.SERVER_ID,
            backend_id=row.BACKEND_ID or "local",
            library_id=row.LIBRARY_ID,
            enabled=bool(row.ENABLED),
            note=row.NOTE or "",
        )
