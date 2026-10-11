"""qBittorrent 403 重登冷却：避免并发/连续 403 触发重登风暴。"""

from typing import Any, cast
from unittest.mock import MagicMock

import qbittorrentapi

from app.downloader.client.qbittorrent import Qbittorrent


def _err() -> Exception:
    return qbittorrentapi.Forbidden403Error("Forbidden")


def _client() -> Qbittorrent:
    c = Qbittorrent.__new__(Qbittorrent)
    c.client_name = "Qbittorrent"
    c.name = "qB439"
    c.qbc = MagicMock()
    c._last_conn_error_at = 0.0
    return c


def test_reauth_cooldown_prevents_storm():
    c = _client()
    qbc = cast(Any, c.qbc)
    assert c._reauth_if_forbidden(_err()) is True
    assert qbc.auth_log_in.call_count == 1
    # 冷却期内再次 403 不再重登
    assert c._reauth_if_forbidden(_err()) is False
    assert qbc.auth_log_in.call_count == 1


def test_reauth_skips_non_forbidden_error():
    c = _client()
    assert c._reauth_if_forbidden(ValueError("boom")) is False
    cast(Any, c.qbc).auth_log_in.assert_not_called()
