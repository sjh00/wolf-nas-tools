"""媒体服务器 user_id 合法性校验测试。

常见误操作：把登录用户名填进 user_id，会让媒体服务器对该 Id 的请求返回 500（如 Emby），
普通用户难以排错。测试连接时应先给出明确提示。
"""

from unittest.mock import patch

import pytest

from app.core.exceptions import MediaServerError
from app.mediaserver.client.emby import Emby
from app.mediaserver.client.jellyfin import Jellyfin

USERS = [{"Id": "abc123", "Name": "admin"}, {"Id": "def456", "Name": "guest"}]


class TestValidateUserId:
    def test_empty_config_skips(self):
        Emby.validate_user_id("", USERS, "Emby")

    def test_users_none_skips(self):
        Emby.validate_user_id("admin", None, "Emby")

    def test_valid_id_passes(self):
        Emby.validate_user_id("abc123", USERS, "Emby")

    def test_username_reports_correct_id(self):
        with pytest.raises(MediaServerError) as err:
            Emby.validate_user_id("admin", USERS, "Emby")
        assert "登录用户名" in str(err.value)
        assert "abc123" in str(err.value)

    def test_unknown_value_raises(self):
        with pytest.raises(MediaServerError):
            Emby.validate_user_id("nobody", USERS, "Emby")


def _emby(user_id: str) -> Emby:
    client = Emby.__new__(Emby)
    client.client_name = "Emby"
    client._host = "http://emby:8096/"
    client._apikey = "KEY"
    client._client_config = {"user_id": user_id}
    client._user = "abc123"
    return client


class TestEmbyGetStatusUserId:
    def test_username_user_id_raises_before_media_query(self):
        client = _emby("admin")
        with (
            patch.object(Emby, "get_users", return_value=USERS),
            patch.object(Emby, "get_medias_count") as mock_count,
        ):
            with pytest.raises(MediaServerError):
                client.get_status()
            mock_count.assert_not_called()

    def test_valid_user_id_reaches_media_query(self):
        client = _emby("abc123")
        with (
            patch.object(Emby, "get_users", return_value=USERS),
            patch.object(Emby, "get_medias_count", return_value=(1, 2, 3)) as mock_count,
        ):
            assert client.get_status() is True
            mock_count.assert_called_once()


def test_jellyfin_username_user_id_raises():
    client = Jellyfin.__new__(Jellyfin)
    client.client_name = "Jellyfin"
    client._host = "http://jellyfin:8096/"
    client._apikey = "KEY"
    client._client_config = {"user_id": "admin"}
    client._user = "abc123"
    with patch.object(Jellyfin, "get_users", return_value=USERS), pytest.raises(MediaServerError):
        client.get_status()
