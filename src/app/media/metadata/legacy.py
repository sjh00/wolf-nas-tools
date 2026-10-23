"""旧 ID（TMDBID / DB: / BG:）到 ProviderRef 的解析."""

from __future__ import annotations

from app.domain.mediatypes import MediaType

from .models import ProviderRef
from .registry import registry

_PREFIXES = {
    "TMDB": "tmdb",
    "DOUBAN": "douban",
    "DB": "douban",
    "BANGUMI": "bangumi",
    "BGM": "bangumi",
    "BG": "bangumi",
    "CONTENT_ID": "content_id",
}


def parse_legacy_ref(raw_id: str | None, media_type: MediaType) -> ProviderRef | None:
    """解析旧字段；纯数字按 TMDB 处理，未知格式返回 None."""
    if raw_id is None:
        return None
    value = str(raw_id).strip()
    if not value or value in {"0", "None", "null", "NULL"}:
        return None

    provider = "tmdb"
    external_id = value
    if ":" in value:
        prefix, rest = value.split(":", 1)
        prefix_key = prefix.strip().upper()
        provider = _PREFIXES.get(prefix_key) or registry.resolve_ref_prefix(prefix_key)
        external_id = rest.strip()
        if not provider or not external_id:
            return None
    elif not value.isdigit():
        return None

    return ProviderRef(provider=provider, external_id=external_id, media_type=media_type)
