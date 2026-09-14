"""下载事件队列 — handler put，SSE get."""

import queue
from typing import Any

import log

download_event_queue: queue.Queue = queue.Queue(maxsize=1000)


def put_download_event(item: dict[str, Any]) -> bool:
    """非阻塞写入下载事件；队列满时丢弃最旧事件再写入，避免阻塞业务线程."""
    try:
        download_event_queue.put_nowait(item)
        return True
    except queue.Full:
        try:
            download_event_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            download_event_queue.put_nowait(item)
            log.warn("[SSE]下载事件队列已满，已丢弃最旧事件")
            return True
        except queue.Full:
            log.warn("[SSE]下载事件队列已满，丢弃当前事件")
            return False
