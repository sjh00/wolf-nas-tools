"""媒体库路由 ORM 仓储。"""

from app.db.models import MediaLibraryRoute
from app.db.repositories.base_repository import BaseRepository


class MediaLibraryRouteRepository(BaseRepository):
    def list(self) -> list[MediaLibraryRoute]:
        with self.session() as db:
            return db.query(MediaLibraryRoute).order_by(MediaLibraryRoute.ID).all()

    def get_profile(self, content_profile: str) -> MediaLibraryRoute | None:
        with self.session() as db:
            return (
                db.query(MediaLibraryRoute)
                .filter(
                    MediaLibraryRoute.CONTENT_PROFILE == content_profile,
                    MediaLibraryRoute.ENABLED.is_(True),
                )
                .first()
            )

    def get(self, route_id: int) -> MediaLibraryRoute | None:
        with self.session() as db:
            return db.query(MediaLibraryRoute).filter(MediaLibraryRoute.ID == int(route_id)).first()

    def upsert(self, values: dict, route_id: int | None = None) -> MediaLibraryRoute:
        with self.session() as db:
            if route_id:
                row = db.query(MediaLibraryRoute).filter(MediaLibraryRoute.ID == int(route_id)).first()
                if row is None:
                    raise ValueError("媒体库路由不存在")
                for key, value in values.items():
                    setattr(row, key, value)
            else:
                row = MediaLibraryRoute(**values)
                db.add(row)
            db.flush()
            return row

    def delete(self, route_id: int) -> int:
        with self.session() as db:
            return db.query(MediaLibraryRoute).filter(MediaLibraryRoute.ID == int(route_id)).delete()
