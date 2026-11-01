"""自定义 RSS 源领域仓储适配器。"""

from app.db.models import CustomRssSource
from app.db.repositories.custom_rss_repository import CustomRssSourceRepository
from app.domain.entities.custom_rss import CustomRssSourceEntity
from app.schemas.auth import UserContext


class CustomRssSourceRepositoryAdapter:
    def __init__(self, repo: CustomRssSourceRepository | None = None):
        self._repo = repo or CustomRssSourceRepository()

    def list(self, user: UserContext | None = None, enabled_only: bool = False) -> list[CustomRssSourceEntity]:
        return [CustomRssSourceEntity.from_orm(row) for row in self._repo.list(user, enabled_only)]

    def get(self, source_id: int, user: UserContext | None = None) -> CustomRssSourceEntity | None:
        row = self._repo.get(source_id, user)
        return CustomRssSourceEntity.from_orm(row) if row is not None else None

    def create(self, entity: CustomRssSourceEntity) -> CustomRssSourceEntity:
        row = CustomRssSource(
            USER_ID=entity.user_id,
            NAME=entity.name,
            URL=entity.url,
            ENABLED=entity.enabled,
            PROXY=entity.proxy,
            COOKIE=entity.cookie,
            HEADERS=entity.headers,
        )
        return CustomRssSourceEntity.from_orm(self._repo.create(row))

    def update(self, entity: CustomRssSourceEntity, user: UserContext | None = None) -> bool:
        values = {
            "NAME": entity.name,
            "URL": entity.url,
            "ENABLED": entity.enabled,
            "PROXY": entity.proxy,
            "COOKIE": entity.cookie,
            "HEADERS": entity.headers,
        }
        return bool(self._repo.update(entity.id, values, user))

    def delete(self, source_id: int, user: UserContext | None = None) -> bool:
        return bool(self._repo.delete(source_id, user))

    def mark_fetch(self, source_id: int, item_count: int, error: str | None = None) -> None:
        self._repo.mark_fetch(source_id, item_count, error)
