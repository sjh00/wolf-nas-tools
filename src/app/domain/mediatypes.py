"""媒体类型值对象."""

from enum import Enum

# 内容画像展示类型的 API 兼容别名：不是核心媒体类型，统一折叠为 movie + profile。
_CONTENT_TYPE_ALIASES: dict[str, tuple[str, str]] = {
    "av": ("movie", "adult"),
}


def normalize_media_type_input(
    value: str | None,
    content_profile: str | None = None,
) -> tuple[str | None, str]:
    """归一化 API 入参中的展示类型别名，返回 (media_type, content_profile)."""
    profile = str(content_profile or "").strip() or "default"
    normalized = str(value or "").strip().lower()
    alias = _CONTENT_TYPE_ALIASES.get(normalized)
    if alias is None:
        return value, profile
    media_type, alias_profile = alias
    if profile == "default":
        profile = alias_profile
    return media_type, profile


class MediaType(Enum):
    TV = "tv"
    MOVIE = "movie"
    ANIME = "anime"
    UNKNOWN = "unknown"

    @property
    def display_name(self) -> str:
        return _MEDIA_TYPE_DISPLAY_NAMES.get(self, "未知")

    @classmethod
    def from_string(cls, value: str) -> "MediaType":
        normalized = str(value).strip().lower()
        aliases = {
            "movie": cls.MOVIE,
            "tv": cls.TV,
            "series": cls.TV,
            "show": cls.TV,
            "anime": cls.ANIME,
            "电影": cls.MOVIE,
            "电视剧": cls.TV,
            "动漫": cls.ANIME,
        }
        return aliases.get(normalized, cls.UNKNOWN)

    def __str__(self) -> str:
        return self.value


_MEDIA_TYPE_DISPLAY_NAMES: dict[MediaType, str] = {
    MediaType.MOVIE: "电影",
    MediaType.TV: "电视剧",
    MediaType.ANIME: "动漫",
    MediaType.UNKNOWN: "未知",
}
