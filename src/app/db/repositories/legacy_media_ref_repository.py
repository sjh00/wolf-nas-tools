"""旧数据中的媒体 ID 读取（只读，用于 P2-2 回填）."""

from __future__ import annotations

from dataclasses import dataclass

from app.db.models.download import DOWNLOADHISTORY
from app.db.models.subscribe import SubscribeMovies, SubscribeTvs
from app.db.models.transfer import TRANSFERHISTORY
from app.db.repositories.base_repository import BaseRepository


@dataclass(frozen=True)
class LegacyMediaRow:
    source: str
    title: str
    year: str | None
    media_type: str
    raw_id: str


class LegacyMediaRefRepository(BaseRepository):
    """读取订阅、下载历史、转移历史中的旧 TMDBID/DB:/BG: 数据."""

    def list_rows(self, *, limit: int | None = None) -> list[LegacyMediaRow]:
        rows: list[LegacyMediaRow] = []
        with self.readonly() as db:
            rows.extend(self._subscribe_rows(db, SubscribeMovies, "movie", "subscribe_movies"))
            rows.extend(self._subscribe_rows(db, SubscribeTvs, "tv", "subscribe_tvs"))
            rows.extend(self._download_rows(db))
            rows.extend(self._transfer_rows(db))
        if limit is not None:
            return rows[:limit]
        return rows

    def _subscribe_rows(self, db, model, media_type: str, source: str) -> list[LegacyMediaRow]:
        return [
            LegacyMediaRow(
                source=source,
                title=row.NAME or "",
                year=row.YEAR or None,
                media_type=media_type,
                raw_id=str(row.TMDBID or ""),
            )
            for row in db.query(model).filter(model.TMDBID.isnot(None)).all()
        ]

    def _download_rows(self, db) -> list[LegacyMediaRow]:
        return [
            LegacyMediaRow(
                source="download_history",
                title=row.TITLE or "",
                year=row.YEAR or None,
                media_type=_normalize_type(row.TYPE),
                raw_id=str(row.TMDBID or ""),
            )
            for row in db.query(DOWNLOADHISTORY).filter(DOWNLOADHISTORY.TMDBID.isnot(None)).all()
        ]

    def _transfer_rows(self, db) -> list[LegacyMediaRow]:
        return [
            LegacyMediaRow(
                source="transfer_history",
                title=row.TITLE or "",
                year=row.YEAR or None,
                media_type=_normalize_type(row.TYPE),
                raw_id=str(row.TMDBID or ""),
            )
            for row in db.query(TRANSFERHISTORY).all()
        ]


def _normalize_type(value: str | None) -> str:
    text = str(value or "").strip().lower()
    if text in {"tv", "series", "show"} or "剧" in text or "综艺" in text:
        return "tv"
    if text in {"anime", "动画", "动漫"} or "动漫" in text:
        return "anime"
    return "movie"
