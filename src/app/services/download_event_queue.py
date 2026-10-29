"""下载事件广播 — 每个 SSE 客户端独立队列，避免新连接收到历史积压."""

from __future__ import annotations

import queue
import threading

_subscribers: set[queue.Queue] = set()
_lock = threading.Lock()


def subscribe_download_events() -> queue.Queue:
    subscriber: queue.Queue = queue.Queue(maxsize=1000)
    with _lock:
        _subscribers.add(subscriber)
    return subscriber


def unsubscribe_download_events(subscriber: queue.Queue) -> None:
    with _lock:
        _subscribers.discard(subscriber)


def publish_download_event(item: dict) -> None:
    with _lock:
        subscribers = list(_subscribers)
    for subscriber in subscribers:
        try:
            subscriber.put_nowait(item)
        except queue.Full:
            continue


# 兼容旧导入；不再作为 SSE 的数据源。
download_event_queue: queue.Queue = queue.Queue(maxsize=1000)
