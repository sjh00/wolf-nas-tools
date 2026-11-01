"""通用题材分类：把各元数据来源统一映射到电影/电视剧/动漫."""

from __future__ import annotations

from typing import Any, Iterable

from app.core.constants import ANIME_GENREIDS
from app.domain.mediatypes import MediaType

_ANIME_GENRE_NAMES = {"动画", "動畫", "アニメ", "animation"}
_ANIME_GENRE_IDS = set(ANIME_GENREIDS)


def is_anime_genre(genres: Iterable[Any] | None) -> bool:
    """兼容 TMDB [{id,name}]、豆瓣 [str] 与插件自定义题材列表."""
    for genre in genres or []:
        if isinstance(genre, dict):
            genre_id = str(genre.get("id") or "").strip()
            name = str(genre.get("name") or "").strip()
        else:
            genre_id = str(genre).strip() if str(genre).strip().isdigit() else ""
            name = str(genre).strip()
        if genre_id and genre_id in _ANIME_GENRE_IDS:
            return True
        if name and name.lower() in _ANIME_GENRE_NAMES:
            return True
    return False


def classify_media_type(
    media_type: MediaType,
    genres: Iterable[Any] | None,
    content_profile: str = "default",
) -> tuple[MediaType, str]:
    """按题材细化分类；动漫仍然存放在电视剧表，但使用 anime 内容画像."""
    if content_profile == "anime":
        return MediaType.ANIME, "anime"
    if media_type in (MediaType.TV, MediaType.ANIME, MediaType.UNKNOWN) and is_anime_genre(genres):
        return MediaType.ANIME, "anime"
    return media_type, content_profile
