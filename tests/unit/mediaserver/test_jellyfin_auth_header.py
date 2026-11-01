"""Jellyfin 12 认证头兼容测试（api_key query 已废弃，需 Authorization 头）."""

from unittest.mock import MagicMock, patch

from app.mediaserver.client.jellyfin import Jellyfin


def _client(apikey: str = "KEY123") -> Jellyfin:
    client = Jellyfin.__new__(Jellyfin)
    client._host = "http://jellyfin:8096/"
    client._apikey = apikey
    client._user = "user-1"
    client._play_host = None
    return client


def test_auth_headers_format():
    """认证头以 MediaBrowser Token 形式携带密钥；附加的 Client/Device 字段不影响兼容性。"""
    headers = _client()._auth_headers()
    assert set(headers) == {"Authorization"}
    assert headers["Authorization"].startswith('MediaBrowser Token="KEY123"')
    # Jellyfin 12+ 已废弃 api_key 查询参数认证，头里不得再出现
    assert "api_key" not in headers["Authorization"]


def test_auth_headers_empty_without_apikey():
    assert _client(apikey="")._auth_headers() == {}


def test_requests_carry_auth_header():
    client = _client()
    with patch("app.mediaserver.client.jellyfin.HttpClient") as http_cls:
        resp = MagicMock()
        resp.json.return_value = [{"Id": "u1"}]
        http_cls.return_value.get.return_value = resp

        client.get_user_count()

    config = http_cls.call_args.kwargs["config"]
    assert config.default_headers["Authorization"].startswith('MediaBrowser Token="KEY123"')
    # URL 中不得再带 api_key 查询参数
    assert "api_key=" not in str(http_cls.return_value.get.call_args.args)
