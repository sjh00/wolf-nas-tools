"""规范剧集解析：来源条目 -> 内部 series_key + 规范季号，不依赖 TMDB."""

import re
from dataclasses import dataclass
from typing import Any

import log
from app.db.repositories.media_series_repository import MediaSeriesRepository
from app.utils.string_utils import StringUtils


def _titles_look_same(a: Any, b: Any) -> bool:
    """两个标题是否指向同一作品（忽略大小写、空格与标点）。"""

    def norm(value: Any) -> str:
        text = str(value or "").strip().lower()
        return re.sub(r"[\W_]+", "", text) if text else ""

    left, right = norm(a), norm(b)
    if not left or not right:
        return False
    return left == right or left in right or right in left


@dataclass
class SeriesResolution:
    series_key: str
    season_number: int
    title: str
    year: str | None
    created: bool = False


class SeriesService:
    def __init__(self, repo: MediaSeriesRepository | None = None):
        self._repo = repo or MediaSeriesRepository()

    @staticmethod
    def split_title_season(title: str) -> tuple[str, int | None]:
        value = str(title or "").strip()
        if not value:
            return "", None
        try:
            parsed = StringUtils.get_keyword_from_string(value)
            base = str(parsed[1] or "").strip() if parsed else ""
            season = parsed[2] if parsed else None
        except Exception:  # noqa: BLE001
            base, season = value, None
        return (base or value), (int(season) if season else None)

    def resolve(
        self,
        *,
        provider: str,
        external_id: str,
        title: str,
        year: str | None = None,
        season_number: int | None = None,
        scope: str = "default",
        total_episodes: int | None = None,
        original_title: str | None = None,
    ) -> SeriesResolution:
        provider = str(provider or "").strip()
        external_id = str(external_id or "").strip()
        if not provider or not external_id:
            base, parsed = self.split_title_season(title)
            return SeriesResolution("", parsed or 1, base, year)

        base, parsed_season = self.split_title_season(title)
        # 单季来源标题里的“第三季/Season 3”优先于前端默认的 season=1
        season = int(parsed_season or season_number or 1)

        alias = self._repo.get_alias(provider, external_id, scope, season)
        if alias is None and season_number is None and parsed_season is None:
            alias = self._repo.get_alias(provider, external_id, scope)
        if alias is not None:
            series = self._repo.get_series(alias.SERIES_KEY)
            if series is not None and self._alias_conflicts(series, base, year):
                # 别名指向的剧集与当前作品明显不符（历史污染：同号错配留下的记录）。
                # 继续沿用会把正确作品的标题覆盖成另一部作品，因此放弃该别名，
                # 改按标题重新匹配，并在下方重建别名指向正确剧集。
                log.warn(
                    f"[Series]别名 {provider}:{external_id} 指向与「{base}」不符的"
                    f"《{series.TITLE}》({series.YEAR})，忽略该别名并重新匹配"
                )
            else:
                return SeriesResolution(
                    series_key=alias.SERIES_KEY,
                    season_number=int(alias.SEASON_NUMBER or 1),
                    title=series.TITLE if series else title,
                    year=series.YEAR if series else year,
                )
        candidates = self._repo.find_series_by_title(base)
        series = None
        if candidates:
            if year:
                same_year = [row for row in candidates if str(row.YEAR or "") == str(year)]
                series = same_year[0] if same_year else candidates[0]
            else:
                series = candidates[0]
        created = False
        if series is None:
            series = self._repo.create_series(
                title=base,
                original_title=original_title,
                year=year,
                provider=provider,
                external_id=external_id,
            )
            created = True

        self._repo.upsert_season(
            series_key=series.SERIES_KEY,
            season_number=season,
            title=str(title or "").strip() or None,
            year=year,
            total_episodes=total_episodes,
            provider=provider,
            external_id=external_id,
        )
        alias_row = self._repo.create_alias(
            provider=provider,
            external_id=external_id,
            scope=scope,
            season_number=season,
            series_key=series.SERIES_KEY,
            confidence=50 if created else 70,
            mapping_source="title_rule",
        )
        if alias_row is None:
            log.warn(f"[Series]别名创建失败，使用新建剧集: {provider}:{external_id}")
        return SeriesResolution(
            series_key=series.SERIES_KEY,
            season_number=season,
            title=series.TITLE,
            year=series.YEAR,
            created=created,
        )

    @staticmethod
    def _alias_conflicts(series: Any, title: str, year: Any) -> bool:
        """别名指向的剧集是否与当前作品矛盾。

        只在「标题不同 **且** 年份也不同」时判定为矛盾：
        - 标题不同但年份相同：多为同一作品的中英文名差异，属于正常情况
        - 年份不同但标题相同：可能是重拍/续作，标题目录仍可复用
        两者同时不符才说明这条别名确实指向另一部作品。
        """
        series_title = getattr(series, "TITLE", None)
        series_year = getattr(series, "YEAR", None)
        if not title or not series_title:
            return False
        if _titles_look_same(title, series_title):
            return False
        text_year = str(year or "").strip()
        text_series_year = str(series_year or "").strip()
        if not text_year or not text_series_year:
            return False
        return text_year != text_series_year

    def get_episode_offset(self, series_key: str | None, season_number: int | None) -> int:
        """读取规范季的集号偏移；连续编号资源与订阅相对集号匹配时使用."""
        key = str(series_key or "").strip()
        if not key or season_number is None:
            return 0
        try:
            season = int(season_number)
        except (TypeError, ValueError):
            return 0
        offset = 0
        try:
            getter = getattr(self._repo, "get_seasons", None)
            rows: Any = getter(key) if callable(getter) else []
            for row in rows or []:
                if int(getattr(row, "SEASON_NUMBER", 0) or 0) == season:
                    offset = max(0, int(getattr(row, "EPISODE_OFFSET", 0) or 0))
                    break
        except Exception:  # noqa: BLE001 - 偏移读取失败按无偏移处理
            offset = 0
        return offset

    def ensure_media_series(self, media) -> str | None:
        """为运行时 MediaInfo 补齐 series_key；无可靠来源时返回 None."""
        current = str(getattr(media, "series_key", "") or "").strip()
        if current:
            return current
        provider = str(getattr(media, "anchor_provider", "") or getattr(media, "provider", "") or "").strip()
        external = str(getattr(media, "anchor_external_id", "") or "").strip()
        metadata_ref = str(getattr(media, "metadata_ref", "") or "").strip()
        if not external and metadata_ref and ":" in metadata_ref:
            provider, external = metadata_ref.split(":", 1)
        tmdb_id = str(getattr(media, "tmdb_id", "") or "").strip()
        if not external and tmdb_id:
            provider, external = "tmdb", tmdb_id
        title = str(getattr(media, "title", "") or getattr(media, "org_string", "") or "").strip()
        if not title:
            return None
        if not provider or not external:
            base, parsed = self.split_title_season(title)
            season = int(getattr(media, "begin_season", 0) or parsed or 1)
            provider, external = "local", f"{base}:{getattr(media, 'year', '') or ''}:S{season}"
        try:
            resolution = self.resolve(
                provider=provider,
                external_id=external,
                title=title,
                year=str(getattr(media, "year", "") or "") or None,
                season_number=getattr(media, "begin_season", None),
                scope=str(getattr(media, "content_profile", "") or "default"),
                total_episodes=getattr(media, "total_episodes", None),
                original_title=getattr(media, "original_title", None),
            )
        except Exception as exc:  # noqa: BLE001 - 剧集解析失败不影响主流程
            log.debug(f"[Series]运行时解析失败: {exc}")
            return None
        media.series_key = resolution.series_key
        return resolution.series_key

    def get_title(self, series_key: str | None) -> str | None:
        if not isinstance(series_key, str) or not series_key.strip():
            return None
        row = self._repo.get_series(series_key)
        return str(row.TITLE) if row is not None and row.TITLE else None

    def list_aliases(self, series_key: str):
        return self._repo.list_aliases(series_key)
