"""Provider ref / legacy mediaid 解析."""

from __future__ import annotations

import re

from .registry import registry


def parse_media_ref(media_ref: str) -> tuple[str, str] | None:
    """按 provider descriptor 的订阅 ID 格式解析 mediaid，不写死 DB/BG."""
    value = str(media_ref or "").strip()
    if not value:
        return None
    if ":" in value:
        prefix, external = value.split(":", 1)
        provider = registry.resolve_ref_prefix(prefix)
        if provider and external:
            return provider, external
    providers = []
    for provider in registry.list_providers():
        descriptor = getattr(provider, "descriptor", None)
        fmt = str(getattr(descriptor, "subscription_id_format", "") or "")
        if descriptor is not None and fmt:
            providers.append((len(fmt.replace("{id}", "")), fmt, descriptor))
    for _literal_len, fmt, descriptor in sorted(providers, reverse=True):
        pattern = "^" + re.escape(fmt).replace(r"\{id\}", r"(?P<id>.+)") + "$"
        match = re.match(pattern, value)
        if match and descriptor is not None:
            return descriptor.provider_key, match.group("id")
    if ":" in value:
        provider, external = value.split(":", 1)
        if registry.get_provider(provider) and external:
            return provider, external
    return None
