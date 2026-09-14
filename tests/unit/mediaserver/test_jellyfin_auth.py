from unittest.mock import MagicMock, patch

from app.mediaserver.client.jellyfin import Jellyfin


def test_auth_header_uses_mediabrowser_token():
    with patch.object(Jellyfin, "get_server_id", return_value="s1"):
        client = Jellyfin(config={"host": "http://127.0.0.1:8096", "api_key": "secret-key", "user_id": "u1"})
    headers = client._auth_headers()
    assert "Authorization" in headers
    assert 'MediaBrowser Token="secret-key"' in headers["Authorization"]
    assert "api_key" not in headers["Authorization"]


def test_users_request_does_not_use_query_api_key():
    with patch.object(Jellyfin, "get_user", return_value="u1"), patch.object(Jellyfin, "get_server_id", return_value="s1"):
        client = Jellyfin(config={"host": "http://127.0.0.1:8096", "api_key": "secret-key", "user_id": "u1"})
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"MovieCount": 1, "SeriesCount": 0, "SongCount": 0}
    with patch.object(client, "_http_get", return_value=mock_resp) as http_get:
        result = client.get_medias_count()
    assert result["MovieCount"] == 1
    url = http_get.call_args[0][0]
    assert "api_key=" not in url
    assert url.endswith("Items/Counts")
