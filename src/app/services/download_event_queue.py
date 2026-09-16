"""下载事件队列 — handler put，SSE get.

每个 SSE 连接订阅独立队列。无人订阅时丢弃事件，避免全局 Queue 积压，
导致打开「正在下载」页时一次性弹出历史 toast。
"""

import queue
import threading
from typing import Any

import log

_subscribers_lock = threading.Lock()
_subscribers: list[queue.Queue] = []
_MAX_SUBSCRIBER_QUEUE = 64

# 兼容旧测试导入；生产路径不再向该队列写入
download_event_queue: queue.Queue = queue.Queue(maxsize=1)


def subscribe_download_events() -> queue.Queue:
    """注册一个 SSE 订阅队列。"""
    q: queue.Queue = queue.Queue(maxsize=_MAX_SUBSCRIBER_QUEUE)
    with _subscribers_lock:
        _subscribers.append(q)
    return q


def unsubscribe_download_events(q: queue.Queue) -> None:
    """取消 SSE 订阅。"""
    with _subscribers_lock:
        try:
            _subscribers.remove(q)
        except ValueError:
            pass


def subscriber_count() -> int:
    with _subscribers_lock:
        return len(_subscribers)


def put_download_event(item: dict[str, Any]) -> bool:
    """广播到所有在线订阅者；无人订阅时丢弃，避免积压。"""
    with _subscribers_lock:
        targets = list(_subscribers)
    if not targets:
        return False
    delivered = False
    for q in targets:
        try:
            q.put_nowait(item)
            delivered = True
        except queue.Full:
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait(item)
                delivered = True
                log.warn("[SSE]下载事件订阅队列已满，已丢弃最旧事件")
            except queue.Full:
                log.warn("[SSE]下载事件订阅队列已满，丢弃当前事件")
    return delivered
