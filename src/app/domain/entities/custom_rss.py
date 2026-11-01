"""自定义 RSS 源领域实体。"""

from dataclasses import dataclass
from datetime import datetime

CUSTOM_RSS_PREFIX = "custom_rss:"


def custom_rss_ref(source_id: int) -> str:
    return f"{CUSTOM_RSS_PREFIX}{int(source_id)}"


def custom_rss_id(ref: str | None) -> int | None:
    if not ref or not ref.startswith(CUSTOM_RSS_PREFIX):
        return None
    value = ref[len(CUSTOM_RSS_PREFIX) :]
    return int(value) if value.isdigit() and int(value) > 0 else None


@dataclass
class CustomRssSourceEntity:
    id: int = 0
    user_id: int | None = None
    name: str = ""
    url: str = ""
    enabled: bool = True
    proxy: bool = False
    cookie: str | None = None
    headers: str | None = None
    last_fetch_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    item_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def ref(self) -> str:
        return custom_rss_ref(self.id)

    @classmethod
    def from_orm(cls, row) -> "CustomRssSourceEntity":
        return cls(
            id=row.ID,
            user_id=row.USER_ID,
            name=row.NAME,
            url=row.URL,
            enabled=bool(row.ENABLED),
            proxy=bool(row.PROXY),
            cookie=row.COOKIE,
            headers=row.HEADERS,
            last_fetch_at=row.LAST_FETCH_AT,
            last_success_at=row.LAST_SUCCESS_AT,
            last_error=row.LAST_ERROR,
            item_count=row.ITEM_COUNT or 0,
            created_at=row.CREATED_AT,
            updated_at=row.UPDATED_AT,
        )
