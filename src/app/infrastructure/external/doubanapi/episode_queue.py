"""豆瓣 HTML 分集后台抓取队列.

单工作者串行抓取，避免并发触发风控；同一 subject+season 只保留一个任务。
调用方可等待结果（刮削需要 NFO）或只入队（预热）。
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Protocol

import log
from app.core.settings import settings

from .episodes import DoubanEpisodeScraper


class EpisodeScraperLike(Protocol):
    def fetch(self, subject_id: str, season: int = 1) -> Any: ...


class EpisodeEnrichmentQueue:
    def __init__(
        self,
        scraper: EpisodeScraperLike | None = None,
        *,
        max_workers: int | None = None,
    ) -> None:
        configured = (settings.get("media") or {}).get("douban_html_episodes_workers", 1)
        self._workers = max(1, int(max_workers or configured or 1))
        self._scraper = scraper or DoubanEpisodeScraper()
        self._executor = ThreadPoolExecutor(max_workers=self._workers, thread_name_prefix="douban-episodes")
        self._futures: dict[tuple[str, int], Future] = {}
        self._lock = threading.Lock()
        self._max_entries = 256

    def submit(self, subject_id: str, season: int = 1) -> Future:
        key = (str(subject_id), int(season))
        with self._lock:
            future = self._futures.get(key)
            if future is None:
                future = self._executor.submit(self._scraper.fetch, key[0], key[1])
                self._futures[key] = future
                future.add_done_callback(lambda item, item_key=key: self._on_done(item_key, item))
                self._evict_locked()
            return future

    def _on_done(self, key: tuple[str, int], future: Future) -> None:
        """失败任务不再永久占用 key；成功结果保留用于去重缓存."""
        try:
            failed = future.exception() is not None
        except Exception:  # noqa: BLE001 - 取消/异常任务
            failed = True
        if not failed:
            return
        with self._lock:
            if self._futures.get(key) is future:
                self._futures.pop(key, None)

    def _evict_locked(self) -> None:
        if len(self._futures) <= self._max_entries:
            return
        for key, future in list(self._futures.items()):
            if future.done():
                self._futures.pop(key, None)
            if len(self._futures) <= self._max_entries:
                break

    def get(self, subject_id: str, season: int = 1, *, wait: bool = True, timeout: float = 180.0):
        future = self.submit(subject_id, season)
        if not wait:
            return ()
        try:
            return future.result(timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - 超时/风控降级
            log.warn(f"[DoubanEpisodes]队列任务未完成 {subject_id} S{season}: {exc}")
            return ()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            pending = sum(1 for future in self._futures.values() if not future.done())
            return {"workers": self._workers, "tracked": len(self._futures), "pending": pending}

    def clear(self) -> None:
        with self._lock:
            self._futures.clear()


episode_queue = EpisodeEnrichmentQueue()
