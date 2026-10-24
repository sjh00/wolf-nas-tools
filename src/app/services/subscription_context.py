"""订阅上下文解析：消息层不再直接依赖订阅仓储."""

from __future__ import annotations

from typing import Any

from app.db.repositories.subscribe_repo_adapter import (
    SubscribeMovieRepositoryAdapter,
    SubscribeTvRepositoryAdapter,
)
from app.domain.mediatypes import MediaType


def resolve_subscription_context(item: Any):
    """按 rssid，退化到 tmdb_id/标题+年份，找到下载所属订阅."""
    rssid = getattr(item, "rssid", None)
    try:
        if getattr(item, "type", None) == MediaType.TV:
            repo = SubscribeTvRepositoryAdapter()
        else:
            repo = SubscribeMovieRepositoryAdapter()
        rows = repo.get_all(rssid=int(rssid)) if rssid else []
        if rows:
            return rows[0]
        tmdbid = str(getattr(item, "tmdb_id", "") or "").strip()
        title = str(getattr(item, "title", "") or "").strip()
        year = str(getattr(item, "year", "") or "").strip()
        for row in repo.get_all():
            if tmdbid and str(getattr(row, "tmdb_id", "") or "") == tmdbid:
                return row
            if title and str(getattr(row, "name", "") or "") == title:
                if not year or str(getattr(row, "year", "") or "") == year:
                    return row
    except Exception:  # noqa: BLE001
        return None
    return None
