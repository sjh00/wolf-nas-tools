"""RedisStore 可用性缓存测试：避免每次操作都 PING Redis，防止阻塞调用方/事件循环."""

import time
from unittest.mock import MagicMock

import pytest

from app.core.settings import settings
from app.infrastructure.redis.store import RedisStore


@pytest.fixture(autouse=True)
def _enable_redis(monkeypatch):
    monkeypatch.setattr(settings.redis, "enabled", True)


def _store_with_client() -> tuple[RedisStore, MagicMock]:
    store = RedisStore()
    client = MagicMock()
    store._client = client
    store._available = True
    return store, client


def test_is_available_uses_cache_without_ping():
    store, client = _store_with_client()
    store._last_ok = time.time()

    assert store.is_available() is True
    client.ping.assert_not_called()


def test_is_available_rechecks_after_interval():
    store, client = _store_with_client()
    store._last_ok = time.time() - (RedisStore._RECHECK_INTERVAL + 1)

    assert store.is_available() is True
    client.ping.assert_called_once()


def test_disabled_redis_does_not_connect(monkeypatch):
    """未启用 Redis 时不创建连接（避免无谓探测与回退日志）."""
    monkeypatch.setattr(settings.redis, "enabled", False)
    store = RedisStore()
    # 未启用时可用性判定为 False，且不触发客户端创建
    assert store.is_available() is False
    assert store.get("k") is None
