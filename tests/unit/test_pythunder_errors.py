"""迅雷下载错误捕获测试：HTTP 状态、API 错误字段与密钥清理."""

import pytest

from app.plugin_framework.builtin_plugins.dl_thunder.backend.pythunder import (
    PyThunder,
    extract_http_error,
    sanitize_error_text,
)

_TORRENT_INFO = {
    "files": [{"id": "f1", "name": "movie.mp4", "file_index": 1, "mime_type": "video/mp4", "size_bytes": 1}],
    "total_files": 1,
    "total_size_bytes": 1,
}


class _Response:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _client(status_code: int, payload=None, text: str = "") -> PyThunder:
    client = PyThunder(token="token-value", host="127.0.0.1", port=2345)
    client.get_pan_token = lambda: "pan-token"  # type: ignore[method-assign]
    client.get_device_id = lambda: "device-id"  # type: ignore[method-assign]
    client.get_torrent_info = lambda *a, **k: _TORRENT_INFO  # type: ignore[method-assign]
    client._client.post = lambda *a, **k: _Response(status_code, payload, text)  # type: ignore[method-assign]
    return client


def test_download_success_returns_task_id():
    client = _client(200, {"task": {"id": "task-1", "name": "movie", "phase": "pending"}})

    result = client.download("magnet:?xt=urn:btih:abc")

    assert result["id"] == "task-1"


def test_download_non_2xx_reports_status_and_api_error():
    client = _client(409, {"error": {"message": "任务已存在", "code": 409}}, text='{"error":"任务已存在"}')

    with pytest.raises(RuntimeError) as exc:
        client.download("magnet:?xt=urn:btih:abc")

    message = str(exc.value)
    assert "HTTP 状态 409" in message
    assert "任务已存在" in message


def test_download_empty_body_reports_status():
    client = _client(500, None, "")

    with pytest.raises(RuntimeError) as exc:
        client.download("magnet:?xt=urn:btih:abc")

    assert "HTTP 状态 500" in str(exc.value)


def test_download_missing_task_id_reports_reason():
    client = _client(200, {"task": {"name": "movie", "phase": "pending"}})

    with pytest.raises(RuntimeError) as exc:
        client.download("magnet:?xt=urn:btih:abc")

    message = str(exc.value)
    assert "HTTP 状态 200" in message
    assert "任务 ID" in message


def test_error_text_hides_tokens_and_magnets():
    raw = (
        "bad request https://x/announce?passkey=secret&token=abc "
        "magnet:?xt=urn:btih:deadbeef&tr=https%3A%2F%2Fx%2Fa%3Fpasskey%3Dx "
        "Authorization: Bearer abc.def Cookie: _jdb_session=cookie-secret; pan_auth=pan-secret"
    )

    cleaned = sanitize_error_text(raw)

    assert "secret" not in cleaned
    assert "deadbeef" not in cleaned
    assert "abc.def" not in cleaned
    assert "cookie-secret" not in cleaned
    assert "pan-secret" not in cleaned
    assert "<magnet>" in cleaned


def test_extract_http_error_handles_nested_message():
    response = _Response(400, {"error": {"message": "save path invalid"}}, '{"error":{"message":"save path invalid"}}')

    assert extract_http_error(response) == "HTTP 状态 400：save path invalid"


def test_builtin_without_task_id_does_not_leak_pan_token():
    client = _client(200, {"name": "movie"})
    client._client.post = lambda *a, **k: _Response(  # type: ignore[method-assign]
        200, {"message": "token=pan-token invalid"}
    )

    with pytest.raises(RuntimeError) as exc:
        client.download("magnet:?xt=urn:btih:abc")

    assert "pan-token" not in str(exc.value)
