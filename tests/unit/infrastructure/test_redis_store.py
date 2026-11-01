"""RedisStore 可用性缓存测试：避免每次操作都 PING Redis，防止阻塞调用方/事件循环."""

import time
from unittest.mock import MagicMock, patch

from app.infrastructure.redis.store import RedisStore


def _cfg(enabled: bool) -> MagicMock:
    return MagicMock(enabled=enabled, host="127.0.0.1", port=6379, password="", db=0)


def test_disabled_redis_does_not_connect():
    """未启用 Redis 时不创建连接（避免无谓探测与回退日志）"""
    with (
        patch("app.infrastructure.redis.store.settings") as settings,
        patch("app.infrastructure.redis.store.StrictRedis") as redis_cls,
    ):
        settings.redis = _cfg(False)
        store = RedisStore()
        assert store.is_available() is False
        assert store.get("k") is None
        redis_cls.assert_not_called()


def test_enabled_redis_connects_when_ping_ok():
    cfg = _cfg(True)
    client = MagicMock()
    with (
        patch("app.infrastructure.redis.store.settings") as settings,
        patch("app.infrastructure.redis.store.StrictRedis", return_value=client) as redis_cls,
    ):
        settings.redis = cfg
        store = RedisStore()
        assert store.is_available() is True
        redis_cls.assert_called_once()
        client.ping.assert_called()
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
