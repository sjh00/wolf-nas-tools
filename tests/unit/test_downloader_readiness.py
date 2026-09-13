"""下载器就绪判定与 Aria2/Thunder 按需重建测试."""

from unittest.mock import MagicMock

from app.downloader.client_factory import DownloadClientFactory
from app.plugin_framework.builtin_plugins.dl_aria2.backend.download_client import Aria2
from app.plugin_framework.builtin_plugins.dl_thunder.backend.download_client import Thunder


class _SessionClient:
    def __init__(self, attr: str, value):
        setattr(self, attr, value)


class _Bare:
    pass


def test_client_ready_detects_session_handles():
    assert DownloadClientFactory._client_ready(_SessionClient("qbc", MagicMock())) is True
    assert DownloadClientFactory._client_ready(_SessionClient("qbc", None)) is False
    assert DownloadClientFactory._client_ready(_SessionClient("trc", MagicMock())) is True
    assert DownloadClientFactory._client_ready(_SessionClient("_client", None)) is False


def test_client_ready_defaults_true_without_handle():
    assert DownloadClientFactory._client_ready(_Bare()) is True


def test_aria2_ensure_connected_rebuilds():
    client = Aria2.__new__(Aria2)
    setattr(client, "_client", None)
    client.init_config = MagicMock(side_effect=lambda: setattr(client, "_client", MagicMock()))

    assert client._ensure_connected() is True
    client.init_config.assert_called_once()


def test_aria2_ensure_connected_false_when_config_missing():
    client = Aria2.__new__(Aria2)
    setattr(client, "_client", None)
    client.init_config = MagicMock()

    assert client._ensure_connected() is False


def test_thunder_ensure_connected_rebuilds():
    client = Thunder.__new__(Thunder)
    setattr(client, "_client", None)
    client.init_config = MagicMock(side_effect=lambda: setattr(client, "_client", MagicMock()))

    assert client._ensure_connected() is True
    client.init_config.assert_called_once()
