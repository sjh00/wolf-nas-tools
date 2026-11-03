"""站点限流的最低间隔兜底。

PT 站点普遍在规则里要求「两次请求间隔不小于 N 秒」（HDSky 等为 60 秒），
超频会被临时限制甚至封禁。历史配置统一是 10/m + burst 10，比 60 秒/次快 10 倍，
且允许瞬间连发 10 个请求。

本模块验证 SiteRateLimiterService 的钳制行为：
- 速率折算出的单次间隔不足下限时拉高
- burst 同步压到 1（否则速率合规仍可突发绕过间隔）
- 未配置速率的站点不再「不限流」
"""

import pytest

from app.infrastructure.rate_limiter.backends import _parse_rate
from app.services.site_rate_limiter import DEFAULT_MIN_INTERVAL_SECONDS, SiteRateLimiterService


def _interval(rate_str: str) -> float:
    count, window = _parse_rate(rate_str)
    return window / count


@pytest.fixture
def svc():
    return SiteRateLimiterService(min_interval_seconds=60)


class TestClampTooFrequent:
    @pytest.mark.parametrize(
        "note",
        [
            {"rate_limit": "10/m", "rate_burst": "10"},
            {"rate_limit": "10/m"},
            {"rate_limit": "2/s"},
            {"rate_limit": "30/m"},
            {"rate_limit": "59/m"},
        ],
    )
    def test_frequent_rates_are_raised_to_min_interval(self, svc, note):
        svc.register_site("s1", note)
        rate_str, burst = svc.get_rate("s1")
        assert _interval(rate_str) >= 60
        assert burst == 1

    def test_legacy_format_is_clamped(self, svc):
        # 旧格式 limit_interval=60 + limit_count=10 → 10/60s → 6 秒一次
        svc.register_site("s1", {"limit_interval": 60, "limit_count": 10})
        rate_str, burst = svc.get_rate("s1")
        assert _interval(rate_str) >= 60
        assert burst == 1

    def test_limit_seconds_below_min_is_clamped(self, svc):
        svc.register_site("s1", {"limit_seconds": 5})
        rate_str, _burst = svc.get_rate("s1")
        assert _interval(rate_str) >= 60


class TestKeepStricterConfig:
    @pytest.mark.parametrize(
        ("note", "expected"),
        [
            ({"rate_limit": "1/m"}, "1/m"),
            ({"rate_limit": "1/2m"}, "1/2m"),
            ({"rate_limit": "1/h"}, "1/h"),
        ],
    )
    def test_configs_at_or_below_min_interval_are_untouched(self, svc, note, expected):
        svc.register_site("s1", note)
        rate_str, _burst = svc.get_rate("s1")
        assert rate_str == expected
        assert _interval(rate_str) >= 60


class TestNoConfigNoLongerUnlimited:
    """未配置速率时早期实现直接不限流 —— 站点漏配即裸奔。"""

    def test_empty_note_gets_min_interval(self, svc):
        svc.register_site("s1", {})
        rate = svc.get_rate("s1")
        assert rate is not None
        assert _interval(rate[0]) >= 60
        assert rate[1] == 1

    def test_none_note_gets_min_interval(self, svc):
        svc.register_site("s1", None)
        rate = svc.get_rate("s1")
        assert rate is not None
        assert _interval(rate[0]) >= 60

    def test_unparsable_rate_falls_back_conservatively(self, svc):
        svc.register_site("s1", {"rate_limit": "garbage"})
        rate_str, burst = svc.get_rate("s1")
        assert _interval(rate_str) >= 60
        assert burst == 1


class TestMinIntervalDisabled:
    def test_zero_disables_clamp(self):
        svc = SiteRateLimiterService(min_interval_seconds=0)
        svc.register_site("s1", {"rate_limit": "10/m", "rate_burst": "10"})
        assert svc.get_rate("s1") == ("10/m", 10)

    def test_zero_keeps_unconfigured_site_unlimited(self):
        svc = SiteRateLimiterService(min_interval_seconds=0)
        svc.register_site("s1", {})
        assert svc.get_rate("s1") is None


class TestDefaults:
    def test_default_min_interval_is_60s(self):
        assert DEFAULT_MIN_INTERVAL_SECONDS == 60

    def test_check_reports_flow_control_after_burst_exhausted(self, svc):
        svc.register_site("s1", {"rate_limit": "10/m", "rate_burst": "10"})
        # 钳制后 burst=1：第一次放行，第二次立即被拦
        assert svc.check("s1", timeout=0) is False
        assert svc.check("s1", timeout=0) is True


class TestEngineToolsPassBurst:
    """engine_tools 必须把 burst 一起传给 HttpClient，否则引擎按 rate 推导回 10。"""

    def test_rate_limit_kwargs_include_burst(self, svc):
        from types import SimpleNamespace

        from app.sites.engine_tools import _get_rate_limit_kwargs

        svc.register_site("7", {"rate_limit": "10/m", "rate_burst": "10"})
        engine = SimpleNamespace(site_limiter=svc)
        site = SimpleNamespace(id=7)
        kwargs = _get_rate_limit_kwargs(engine, site)
        assert kwargs["rate_limit_key"] == "site:7"
        assert kwargs["rate_limit_rate"] == "1/60s"
        assert kwargs.get("rate_limit_burst") == 1

    def test_missing_site_limiter_returns_empty(self):
        from types import SimpleNamespace

        from app.sites.engine_tools import _get_rate_limit_kwargs

        assert _get_rate_limit_kwargs(SimpleNamespace(), SimpleNamespace(id=1)) == {}
