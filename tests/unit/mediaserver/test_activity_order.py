"""媒体服务器最近动态排序测试。"""

from unittest.mock import MagicMock, patch

from app.mediaserver.client.emby import Emby
from app.mediaserver.client.jellyfin import Jellyfin


def _response():
    response = MagicMock()
    response.json.return_value = {
        "Items": [
            {"Type": "VideoPlayback", "Name": "旧记录", "Date": "2024-01-01T00:00:00Z"},
            {"Type": "VideoPlayback", "Name": "新记录", "Date": "2026-01-01T00:00:00Z"},
        ]
    }
    return response


def test_emby_activity_is_sorted_newest_first():
    client = Emby.__new__(Emby)
    client._host = "http://emby/"
    client._apikey = "key"
    with patch("app.mediaserver.client.emby.HttpClient") as http_client:
        http_client.return_value.get.return_value = _response()
        result = client.get_activity_log(10)
        request_url = http_client.return_value.get.call_args.args[0]
    assert [item["event"] for item in result] == ["新记录", "旧记录"]
    assert "SortOrder=Descending" in request_url


def test_emby_accepts_new_activity_event_names():
    client = Emby.__new__(Emby)
    client._host = "http://emby/"
    client._apikey = "key"
    response = _response()
    response.json.return_value = {
        "Items": [
            {"Type": "playback.start", "Name": "开始播放示例", "Date": "2026-01-01T00:00:00Z"},
            {
                "Type": "user.authenticated",
                "Name": "用户已验证",
                "ShortOverview": "iPhone",
                "Date": "2025-01-01T00:00:00Z",
            },
            {"Type": "system.backupcompleted", "Name": "备份完成", "Date": "2024-01-01T00:00:00Z"},
        ]
    }
    with patch("app.mediaserver.client.emby.HttpClient") as http_client:
        http_client.return_value.get.return_value = response
        result = client.get_activity_log(10)
    assert [item["type"] for item in result] == ["PL", "LG"]
    assert [item["event"] for item in result] == ["开始播放示例", "用户已验证, iPhone"]


def test_jellyfin_activity_is_sorted_newest_first():
    client = Jellyfin.__new__(Jellyfin)
    client._host = "http://jellyfin/"
    client._apikey = "key"
    client._auth_headers = MagicMock(return_value={})
    with patch("app.mediaserver.client.jellyfin.HttpClient") as http_client:
        http_client.return_value.get.return_value = _response()
        result = client.get_activity_log(10)
        request_url = http_client.return_value.get.call_args.args[0]
    assert [item["event"] for item in result] == ["新记录", "旧记录"]
    assert "SortOrder=Descending" in request_url
