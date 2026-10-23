"""来源无关的媒体引用与合成主体."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.mediatypes import MediaType


@dataclass(frozen=True)
class MediaRef:
    """上层统一使用的媒体锚点；不携带任何 provider 专属结构."""

    provider: str
    external_id: str
    scope: str = "default"
    media_type: MediaType | None = None


@dataclass
class MediaSubject:
    """供 Composer 使用的最小媒体主体，替代 SimpleNamespace/MediaInfo 鸭子类型."""

    media_type: MediaType
    tmdb_id: str = ""
    douban_id: str | None = None
    anchor_provider: str = ""
    anchor_external_id: str = ""
    content_profile: str = "default"
    title: str | None = None
    year: str | None = None
    keyword: str | None = None
    begin_season: int | None = None
    extra: dict[str, Any] | None = None

    @property
    def type(self) -> MediaType:
        return self.media_type

    def get_season_seq(self) -> int:
        return int(self.begin_season or 0)

    def get_media_ref(self) -> MediaRef | None:
        if self.anchor_provider and self.anchor_external_id:
            return MediaRef(
                provider=self.anchor_provider,
                external_id=self.anchor_external_id,
                media_type=self.media_type,
            )
        if str(self.tmdb_id or "").isdigit():
            return MediaRef(provider="tmdb", external_id=str(self.tmdb_id), media_type=self.media_type)
        if self.douban_id:
            return MediaRef(provider="douban", external_id=str(self.douban_id), media_type=self.media_type)
        return None
