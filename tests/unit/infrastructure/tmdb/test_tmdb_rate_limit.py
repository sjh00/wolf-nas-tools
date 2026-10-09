"""TMDB 限流优化测试：按 API Key 限流、速率可配、Retry-After 处理。"""

from typing import Any, cast
from unittest.mock import MagicMock

from app.infrastructure.external.tmdbv3api import tmdb as tmdb_mod
from app.infrastructure.external.tmdbv3api.tmdb import TMDb
from app.infrastructure.tmdb import rate_limiter as rl_mod
from app.infrastructure.tmdb.rate_limiter import (
    TMDBRateLimiter,
    _retry_after_seconds,
    _RetryAfterOrExponential,
    _should_retry_tmdb,
)


class _Resp:
    def __init__(self, headers, status_code=None):
        self.headers = headers
        self.status_code = status_code


class _Exc(Exception):
    def __init__(self, headers=None, status_code=None):
        self.response = _Resp(headers or {}, status_code)
        self.status_code = status_code


class _State:
    def __init__(self, exc):
        self.outcome = MagicMock()
        self.outcome.exception.return_value = exc


def test_retry_after_seconds_reads_header():
    assert _retry_after_seconds(_Exc({"retry-after": "2.5"})) == 2.5
    assert _retry_after_seconds(_Exc({})) is None


def test_retry_after_wait_used_when_present():
    base = MagicMock(return_value=7.0)
    wait = _RetryAfterOrExponential(base)

    assert wait(cast(Any, _State(_Exc({"retry-after": "3"})))) == 3.0
    assert wait(cast(Any, _State(ValueError("boom")))) == 7.0


def test_should_retry_tmdb_status_codes():
    assert _should_retry_tmdb(_Exc(status_code=429)) is True
    assert _should_retry_tmdb(_Exc(status_code=503)) is True
    assert _should_retry_tmdb(_Exc(status_code=404)) is False


def test_tmdb_rate_limiter_uses_configured_rate(monkeypatch):
    engine = MagicMock()
    engine.acquire.return_value = True
    limiter = TMDBRateLimiter(engine=engine)
    monkeypatch.setattr(rl_mod, "settings", MagicMock(get=lambda *a, **k: {"tmdb_rate": "20/10s"}))

    assert limiter.acquire("KEY") is True
    engine.acquire.assert_called_once_with("tmdb:KEY", rate="20/10s", timeout=30)


def test_call_rate_limits_per_api_key(monkeypatch):
    tmdb = TMDb()
    tmdb.api_key = "KEY"
    tmdb.domain = "https://api.themoviedb.org/3"

    response = MagicMock()
    response.headers = {}
    response.json.return_value = {}
    client = MagicMock()
    client.request.return_value = response

    monkeypatch.setattr(tmdb, "_get_client", lambda: client)
    monkeypatch.setattr(tmdb_mod, "get_retry_handler", lambda: MagicMock(execute=lambda fn: fn()))
    monkeypatch.setattr(tmdb_mod, "settings", MagicMock(get=lambda *a, **k: {"tmdb_rate": "20/10s"}))

    tmdb._call("/movie/1", "")

    _, kwargs = client.request.call_args
    assert kwargs["rate_limit_key"] == "tmdb:KEY"
    assert kwargs["rate_limit_rate"] == "20/10s"
