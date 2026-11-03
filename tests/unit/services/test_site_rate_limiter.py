"""SiteRateLimiterService 单元测试.

本文件只验证**配置解析**（新旧格式、数值类型、异常值回退），
因此统一用 ``min_interval_seconds=0`` 关闭最低间隔兜底，避免断言被钳制影响。
兜底策略本身见 tests/unit/services/test_site_min_interval.py。
"""

from unittest.mock import MagicMock

from app.services.site_rate_limiter import SiteRateLimiterService


def _svc(engine=None):
    """关闭最低间隔兜底的实例：只测配置解析逻辑."""
    return SiteRateLimiterService(engine=engine, min_interval_seconds=0)


class TestSiteRateLimiterServiceRegister:
    def test_register_site_with_string_rate_limit(self):
        engine = MagicMock()
        engine.acquire.return_value = True
        svc = _svc(engine)
        svc.register_site("yema", {"rate_limit": "10/m", "rate_burst": "10"})
        config = svc.get_rate("yema")
        assert config is not None
        rate, burst = config
        assert rate == "10/m"
        assert burst == 10
        assert svc.check("yema") is False
        engine.acquire.assert_called_once()

    def test_register_site_with_old_string_format(self):
        engine = MagicMock()
        engine.acquire.return_value = True
        svc = _svc(engine)
        svc.register_site("zmpt", {"limit_interval": "60", "limit_count": "10"})
        config = svc.get_rate("zmpt")
        assert config is not None
        rate, burst = config
        assert rate == "10/60s"
        assert burst == 10
        assert svc.check("zmpt") is False

    def test_register_site_with_numeric_values(self):
        engine = MagicMock()
        engine.acquire.return_value = True
        svc = _svc(engine)
        svc.register_site("mteam", {"rate_limit": "5/s", "rate_burst": 5})
        config = svc.get_rate("mteam")
        assert config is not None
        rate, burst = config
        assert rate == "5/s"
        assert burst == 5

    def test_register_site_no_limit(self):
        engine = MagicMock()
        svc = _svc(engine)
        svc.register_site("none", {})
        assert svc.get_rate("none") is None
        assert svc.check("none") is False
        engine.acquire.assert_not_called()

    def test_check_rate_limit_hit(self):
        engine = MagicMock()
        engine.acquire.return_value = False
        svc = _svc(engine)
        svc.register_site("hit", {"rate_limit": "1/m"})
        assert svc.check("hit") is True

    def test_register_site_invalid_values_default_to_no_limit(self):
        svc = _svc()
        svc.register_site("bad", {"limit_interval": "abc", "limit_count": "xyz"})
        assert svc.get_rate("bad") is None
