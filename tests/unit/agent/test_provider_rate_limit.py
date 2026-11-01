"""LLM 并发限流 + 429 退避重试 与 识别降级测试。"""

from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from app.agent.agents.media_recognizer import MediaRecognizer
from app.agent.providers import base as base_mod
from app.agent.providers.base import LLMThrottle
from app.infrastructure.rate_limiter import RateLimitEngine
from app.infrastructure.rate_limiter.backends import MemoryTokenBucketBackend, RedisTokenBucketBackend


class _FakeRateLimit(Exception):
    status_code = 429


class _FakeRedis:
    """最小 zset 语义，用于验证 Redis 并发限流逻辑。"""

    def __init__(self):
        self._z: dict[str, dict[str, float]] = {}

    def is_available(self) -> bool:
        return True

    def zremrangebyscore(self, name, min_score, max_score) -> int:
        data = self._z.get(name, {})
        for member in [m for m, score in data.items() if score <= max_score]:
            del data[member]
        return 0

    def zcard(self, name) -> int:
        return len(self._z.get(name, {}))

    def zadd(self, name, mapping) -> int:
        self._z.setdefault(name, {}).update(mapping)
        return 1

    def expire(self, name, seconds) -> int:
        return 1

    def zrem(self, name, *members) -> int:
        data = self._z.get(name, {})
        for member in members:
            data.pop(member, None)
        return 1


def test_is_rate_limit_error_detects_status_429():
    assert base_mod._is_rate_limit_error(_FakeRateLimit()) is True
    assert base_mod._is_rate_limit_error(ValueError("boom")) is False


def test_llm_throttle_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(base_mod.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _FakeRateLimit()
        return "OK"

    assert LLMThrottle.call(fn, max_retries=3) == "OK"
    assert calls["n"] == 2


def test_llm_throttle_raises_after_retries_exhausted(monkeypatch):
    monkeypatch.setattr(base_mod.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise _FakeRateLimit()

    with pytest.raises(_FakeRateLimit):
        LLMThrottle.call(fn, max_retries=2)
    assert calls["n"] == 3  # 首次 + 2 次重试


def test_get_llm_engine_reads_config(monkeypatch):
    LLMThrottle.reset()
    fake_settings = MagicMock()
    fake_settings.get.return_value = {"max_concurrency": 3}
    monkeypatch.setattr(base_mod, "settings", fake_settings)

    _engine, limit = base_mod._get_llm_engine()
    assert limit == 3
    LLMThrottle.reset()


def test_memory_concurrency_unlimited():
    engine = RateLimitEngine(backend=MemoryTokenBucketBackend())
    assert engine.acquire_concurrency("llm", 0) == ""


def test_memory_concurrency_blocks_until_release():
    engine = RateLimitEngine(backend=MemoryTokenBucketBackend())
    token = engine.acquire_concurrency("llm", 1)
    assert token
    assert engine.acquire_concurrency("llm", 1, timeout=0.05) is None
    engine.release_concurrency("llm", token)
    token2 = engine.acquire_concurrency("llm", 1, timeout=0.05)
    assert token2
    engine.release_concurrency("llm", token2)


def test_redis_concurrency_distributed_limit():
    backend = RedisTokenBucketBackend.__new__(RedisTokenBucketBackend)
    backend._redis = cast(Any, _FakeRedis())
    backend._conc_ttl = 300

    token = backend.acquire_concurrency("llm", 1)
    assert token
    assert backend.acquire_concurrency("llm", 1, timeout=0.05) is None
    backend.release_concurrency("llm", token)
    assert backend.acquire_concurrency("llm", 1, timeout=0.05)


def test_recognize_degrades_to_none_on_error():
    svc = MagicMock()
    svc.ready = True
    svc.structured_chat.side_effect = RuntimeError("429 rate limited")

    assert MediaRecognizer(svc).recognize("Some.Movie.2020.mkv") is None
