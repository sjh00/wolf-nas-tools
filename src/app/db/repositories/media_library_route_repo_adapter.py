"""媒体库路由领域仓储适配器。"""

from app.db.repositories.media_library_route_repository import MediaLibraryRouteRepository
from app.domain.entities.media_library_route import MediaLibraryRouteEntity


class MediaLibraryRouteRepositoryAdapter:
    def __init__(self, repo: MediaLibraryRouteRepository | None = None):
        self._repo = repo or MediaLibraryRouteRepository()

    def list(self) -> list[MediaLibraryRouteEntity]:
        return [MediaLibraryRouteEntity.from_orm(row) for row in self._repo.list()]

    def get_profile(self, content_profile: str) -> MediaLibraryRouteEntity | None:
        row = self._repo.get_profile(content_profile)
        return MediaLibraryRouteEntity.from_orm(row) if row is not None else None

    def get(self, route_id: int) -> MediaLibraryRouteEntity | None:
        row = self._repo.get(route_id)
        return MediaLibraryRouteEntity.from_orm(row) if row is not None else None

    def upsert(self, entity: MediaLibraryRouteEntity) -> MediaLibraryRouteEntity:
        values = {
            "CONTENT_PROFILE": entity.content_profile,
            "TARGET_PATH": entity.target_path,
            "SERVER_ID": entity.server_id,
            "LIBRARY_ID": entity.library_id,
            "ENABLED": entity.enabled,
            "NOTE": entity.note,
        }
        row = self._repo.upsert(values, entity.id or None)
        return MediaLibraryRouteEntity.from_orm(row)

    def delete(self, route_id: int) -> bool:
        return bool(self._repo.delete(route_id))
