"""ParserProfile 解析器链：高置信度内容编号识别可短路通用解析."""

from __future__ import annotations

from typing import Any

from .registry import MetadataRegistry
from .registry import registry as global_registry


class ParserChain:
    def __init__(self, *, registry: MetadataRegistry | None = None) -> None:
        self._registry = registry or global_registry

    def extract(self, title: str, subtitle: str = "") -> Any | None:
        profiles = [profile for profile in self._registry.list_profiles("parser") if getattr(profile, "extract", None)]
        profiles.sort(key=lambda profile: getattr(profile, "priority", 0), reverse=True)
        for profile in profiles:
            try:
                result = profile.extract(title, subtitle)
            except Exception:
                continue
            if result is not None:
                return result
        return None
