"""Transmission 客户端按需重连测试."""

from unittest.mock import MagicMock

from app.downloader.client.transmission import Transmission


def _bare_client():
    client = Transmission.__new__(Transmission)
    client.trc = None
    client.host = "127.0.0.1"
    client.port = 9091
    client.name = "DownloaderTR"
    return client


def test_ensure_connected_relogins_when_missing():
    client = _bare_client()
    client.connect = MagicMock(side_effect=lambda: setattr(client, "trc", MagicMock()))

    assert client._ensure_connected() is True
    client.connect.assert_called_once()


def test_ensure_connected_returns_false_when_login_fails():
    client = _bare_client()
    client.connect = MagicMock()

    assert client._ensure_connected() is False


def test_ensure_connected_short_circuits_when_session_present():
    client = _bare_client()
    client.trc = MagicMock()
    client.connect = MagicMock()

    assert client._ensure_connected() is True
    client.connect.assert_not_called()
