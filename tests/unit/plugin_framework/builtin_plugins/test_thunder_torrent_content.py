"""迅雷下载器：二进制种子经插件序列化后仍应能还原为 bytes."""

from typing import Any, cast
from unittest.mock import MagicMock

from app.plugin_framework.builtin_plugins.dl_thunder.backend.download_client import Thunder


def _client():
    client = Thunder.__new__(Thunder)
    client._client = MagicMock()
    client._client.torrent_to_magnet.return_value = "magnet:?xt=urn:btih:abc"
    client._client._resolve_folder_id.return_value = "folder"
    client._client.download.return_value = {"id": "task-1"}
    client._last_add_error = ""
    return client


def test_thunder_accepts_byte_list():
    client = _client()
    content = list(b"d4:infod4:name4:testee")
    assert cast(Any, client.add_torrent_and_get_id)(content) == "task-1"
    cast(Any, client._client).download.assert_called_once()


def test_thunder_accepts_wrapped_bytes_dict():
    client = _client()
    content = {"content": b"d4:infod4:name4:testee"}
    assert cast(Any, client.add_torrent_and_get_id)(content) == "task-1"
    cast(Any, client._client).download.assert_called_once()


def test_torrent_bytes_generate_magnet_locally():
    info = b"d6:lengthi1e4:name4:test12:piece lengthi16384e6:pieces0:e"
    torrent = b"d8:announce14:http://tracker4:info" + info + b"e"
    magnet = Thunder._torrent_bytes_to_magnet(torrent)
    assert magnet is not None
    assert magnet.startswith("magnet:?xt=urn:btih:")
    assert "dn=test" in magnet
    assert "tr=http%3A%2F%2Ftracker" in magnet
    import hashlib

    assert hashlib.sha1(info).hexdigest() in magnet


def test_select_only_main_video_from_mixed_torrent():
    import bencodepy

    torrent = bencodepy.encode(
        {
            "info": {
                "name": "achj-097",
                "files": [
                    {"length": 175, "path": ["2026英超官方网站.url"]},
                    {"length": 7900000000, "path": ["achj-097ch.mp4"]},
                    {"length": 175, "path": ["全网最劲体育电竞直播平台.url"]},
                    {"length": 66000000, "path": ["苍老师强力推荐.mp4"]},
                ],
                "piece length": 16384,
                "pieces": b"",
            }
        }
    )
    assert Thunder._select_media_file_indices(torrent) == "1"
