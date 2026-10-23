"""刮削后处理器扩展点.

插件通过 PluginContext 注册，核心只负责调度；禁用插件时按 plugin_id 注销。
"""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Any

import log

SnapshotProcessor = Callable[[Any], None]
PosterProcessor = Callable[[str, Any], str | None]
WatermarkProcessor = Callable[[str, Any], int]

_PROCESSOR_KINDS = frozenset({"snapshot", "poster", "watermark"})


class ScraperProcessorRegistry:
    """线程安全的刮削后处理器注册表."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._processors: dict[str, dict[str, Callable[..., Any]]] = {kind: {} for kind in _PROCESSOR_KINDS}

    def register(self, plugin_id: str, kind: str, processor: Callable[..., Any]) -> None:
        if kind not in _PROCESSOR_KINDS:
            raise ValueError(f"未知刮削处理器类型: {kind}")
        with self._lock:
            self._processors[kind][plugin_id] = processor

    def unregister_plugin(self, plugin_id: str) -> None:
        with self._lock:
            for processors in self._processors.values():
                processors.pop(plugin_id, None)

    def enrich_snapshot(self, snapshot: Any) -> None:
        with self._lock:
            processors = list(self._processors["snapshot"].values())
        for processor in processors:
            try:
                processor(snapshot)
            except Exception as exc:  # noqa: BLE001 - 单个处理器失败不阻断刮削
                log.warn(f"[Scraper]快照处理器失败: {exc}")

    def process_poster(self, path: str, snapshot: Any) -> list[str]:
        with self._lock:
            processors = list(self._processors["poster"].values())
        modes: list[str] = []
        for processor in processors:
            try:
                mode = processor(path, snapshot)
            except Exception as exc:  # noqa: BLE001 - 单个处理器失败不阻断刮削
                log.warn(f"[Scraper]封面处理器失败: {exc}")
                continue
            if mode:
                modes.append(mode)
        return modes

    def process_watermark(self, target_dir: str, snapshot: Any) -> int:
        with self._lock:
            processors = list(self._processors["watermark"].values())
        applied = 0
        for processor in processors:
            try:
                applied += int(processor(target_dir, snapshot) or 0)
            except Exception as exc:  # noqa: BLE001 - 单个处理器失败不阻断刮削
                log.warn(f"[Scraper]水印处理器失败: {exc}")
        return applied


scraper_processor_registry = ScraperProcessorRegistry()
