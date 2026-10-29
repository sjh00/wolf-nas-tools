"""下载事件广播：新订阅者不能收到历史事件."""

from app.services.download_event_queue import (
    publish_download_event,
    subscribe_download_events,
    unsubscribe_download_events,
)


def test_new_subscriber_gets_only_future_events():
    old = subscribe_download_events()
    publish_download_event({"event": "download.completed", "data": {"name": "old"}})
    assert old.get(timeout=1)["data"]["name"] == "old"
    unsubscribe_download_events(old)

    new = subscribe_download_events()
    assert new.empty()
    publish_download_event({"event": "download.completed", "data": {"name": "new"}})
    assert new.get(timeout=1)["data"]["name"] == "new"
    unsubscribe_download_events(new)
