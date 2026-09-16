"""下载事件队列单元测试."""

import queue

from app.services.download_event_queue import (
    put_download_event,
    subscribe_download_events,
    subscriber_count,
    unsubscribe_download_events,
)


class TestDownloadEventQueue:
    def test_no_subscriber_drops_event(self):
        assert subscriber_count() >= 0
        if subscriber_count() == 0:
            assert put_download_event({"event": "test", "data": {}}) is False

    def test_broadcast_to_subscribers(self):
        q1 = subscribe_download_events()
        q2 = subscribe_download_events()
        try:
            assert put_download_event({"event": "download.started", "data": {"k": "v"}}) is True
            assert q1.get(timeout=1)["data"]["k"] == "v"
            assert q2.get(timeout=1)["data"]["k"] == "v"
        finally:
            unsubscribe_download_events(q1)
            unsubscribe_download_events(q2)

    def test_unsubscribe_stops_delivery(self):
        q = subscribe_download_events()
        unsubscribe_download_events(q)
        put_download_event({"event": "x", "data": {}})
        try:
            q.get(timeout=0.01)
            raise AssertionError("unsubscribed queue should not receive events")
        except queue.Empty:
            pass
