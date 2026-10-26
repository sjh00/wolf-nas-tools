"""自定义 RSS 源 ORM 仓储。"""

from datetime import datetime
from typing import Any

from app.db.models import CustomRssSource
from app.db.repositories.base_repository import BaseRepository
from app.db.repositories.data_scope import apply_owner_scope
from app.schemas.auth import UserContext


class CustomRssSourceRepository(BaseRepository):
    def list(self, user: UserContext | None = None, enabled_only: bool = False) -> list[CustomRssSource]:
        with self.session() as db:
            query = db.query(CustomRssSource)
            if user is not None:
                query = apply_owner_scope(query, CustomRssSource, user)
            if enabled_only:
                query = query.filter(CustomRssSource.ENABLED.is_(True))
            return query.order_by(CustomRssSource.ENABLED.desc(), CustomRssSource.ID.desc()).all()

    def get(self, source_id: int, user: UserContext | None = None) -> CustomRssSource | None:
        with self.session() as db:
            query = db.query(CustomRssSource).filter(CustomRssSource.ID == int(source_id))
            if user is not None:
                query = apply_owner_scope(query, CustomRssSource, user)
            return query.first()

    def create(self, row: CustomRssSource) -> CustomRssSource:
        with self.session() as db:
            db.add(row)
            db.flush()
            return row

    def update(self, source_id: int, values: dict, user: UserContext | None = None) -> int:
        with self.session() as db:
            query = db.query(CustomRssSource).filter(CustomRssSource.ID == int(source_id))
            if user is not None:
                query = apply_owner_scope(query, CustomRssSource, user)
            update_values: dict[Any, Any] = {**values, "UPDATED_AT": datetime.now()}
            return query.update(update_values, synchronize_session=False)

    def delete(self, source_id: int, user: UserContext | None = None) -> int:
        with self.session() as db:
            query = db.query(CustomRssSource).filter(CustomRssSource.ID == int(source_id))
            if user is not None:
                query = apply_owner_scope(query, CustomRssSource, user)
            return query.delete(synchronize_session=False)

    def mark_fetch(self, source_id: int, item_count: int, error: str | None = None) -> None:
        now = datetime.now()
        values: dict[Any, Any] = {
            "LAST_FETCH_AT": now,
            "LAST_ERROR": error[:2000] if error else None,
            "ITEM_COUNT": item_count,
        }
        if not error:
            values["LAST_SUCCESS_AT"] = now
        with self.session() as db:
            db.query(CustomRssSource).filter(CustomRssSource.ID == int(source_id)).update(
                values, synchronize_session=False
            )
