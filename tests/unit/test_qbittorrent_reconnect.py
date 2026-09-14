"""qBittorrent 客户端按需重连测试."""

from unittest.mock import MagicMock

from app.downloader.client.qbittorrent import Qbittorrent


def _bare_client():
    client = Qbittorrent.__new__(Qbittorrent)
    client.qbc = None
    client.host = "192.168.50.153"
    client.port = 8889
    client.client_name = "Qbittorrent"
    client.name = "DownloaderQB"
    return client


def test_ensure_connected_relogins_when_missing():
    client = _bare_client()
    client.connect = MagicMock(side_effect=lambda: setattr(client, "qbc", MagicMock()))

    assert client._ensure_connected() is True
    client.connect.assert_called_once()


def test_ensure_connected_returns_false_when_login_fails():
    client = _bare_client()
    client.connect = MagicMock()

    assert client._ensure_connected() is False


def test_ensure_connected_short_circuits_when_session_present():
    client = _bare_client()
    client.qbc = MagicMock()
    client.connect = MagicMock()

    assert client._ensure_connected() is True
    client.connect.assert_not_called()
