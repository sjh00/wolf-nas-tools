"""迅雷多文件任务保留种子根目录名测试."""

import json
from unittest.mock import MagicMock

from app.plugin_framework.builtin_plugins.dl_thunder.backend.pythunder import PyThunder


def test_multi_file_task_uses_torrent_root_name():
    thunder = PyThunder()
    thunder.get_torrent_info = MagicMock(
        return_value={
            "root_name": "ROOT_FOLDER",
            "files": [
                {
                    "name": "file1.mp4",
                    "size_bytes": 5,
                    "file_index": 1,
                    "mime_type": "video/mp4",
                    "id": "1",
                },
                {
                    "name": "file2.jpg",
                    "size_bytes": 5,
                    "file_index": 2,
                    "mime_type": "image/jpeg",
                    "id": "2",
                },
            ],
            "total_files": 2,
            "total_size_bytes": 10,
        }
    )
    thunder.get_device_id = MagicMock(return_value="device")
    thunder.get_pan_token = MagicMock(return_value="token")
    response = MagicMock(status_code=200)
    response.json.return_value = {"id": "task-1"}
    thunder._client = MagicMock()
    thunder._client.post.return_value = response

    thunder.download("magnet:?xt=urn:btih:abc", destination_path="/downloads/xunlei/")

    payload = json.loads(thunder._client.post.call_args.kwargs["data"])
    assert payload["name"] == "ROOT_FOLDER"
    assert payload["file_name"] == "file1.mp4"
