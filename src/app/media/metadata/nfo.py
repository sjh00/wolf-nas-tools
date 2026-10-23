"""NFO Profile 扩展：插件可向快照 NFO 追加标签."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .registry import MetadataRegistry
from .registry import registry as global_registry


@dataclass(frozen=True)
class NfoProfile:
    key: str
    content_profile: str = "default"
    extra_tags: Callable[[Any], dict[str, Any]] | None = None
    templates: dict[str, str] = field(default_factory=dict)


def register_nfo_profile(
    profile: NfoProfile,
    *,
    registry: MetadataRegistry | None = None,
    plugin_id: str = "builtin",
) -> None:
    (registry or global_registry).register_profile("nfo", profile.key, profile, plugin_id=plugin_id)


def list_nfo_profiles(registry: MetadataRegistry | None = None) -> list[NfoProfile]:
    return [item for item in (registry or global_registry).list_profiles("nfo") if isinstance(item, NfoProfile)]


def render_nfo_extra_tags(
    snapshot: Any,
    registry: MetadataRegistry | None = None,
) -> dict[str, Any]:
    tags: dict[str, Any] = {}
    extra = getattr(snapshot, "extra", {}) or {}
    for profile in list_nfo_profiles(registry):
        profile_key = profile.content_profile
        matched = profile_key in {snapshot.content_profile, "default"}
        if not matched and profile_key:
            prefix = f"{profile_key}."
            matched = any(str(key).startswith(prefix) for key in extra)
        if not matched:
            continue
        if profile.extra_tags is None:
            continue
        try:
            tags.update(profile.extra_tags(snapshot) or {})
        except Exception:
            continue
    return tags
