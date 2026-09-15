"""速率限制中间件集成测试."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.infrastructure.rate_limiter.middleware import RateLimitMiddleware


@pytest.fixture
def mock_redis_unavailable():
    """模拟 Redis 不可用，使用内存后端"""
    with patch("app.infrastructure.rate_limiter.backends.RedisStore") as mock_cls:
        mock_store = mock_cls.return_value
        mock_store.is_available.return_value = False
        yield


class TestRateLimitMiddleware:
    def test_exempt_paths_bypass_limit(self, mock_redis_unavailable):
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, rate="1/m")

        @app.get("/health")
        def health():
            return {"status": "ok"}

        client = TestClient(app)
        for _ in range(5):
            response = client.get("/health")
            assert response.status_code == 200

    def test_blocks_when_limit_reached(self, mock_redis_unavailable):
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, rate="2/m")

        @app.get("/api/test")
        def test_endpoint():
            return {"data": "ok"}

        client = TestClient(app)
        assert client.get("/api/test").status_code == 200
        assert client.get("/api/test").status_code == 200
        response = client.get("/api/test")
        assert response.status_code == 429
        assert "请求过于频繁" in response.text

    def test_uses_x_forwarded_for_header(self, mock_redis_unavailable):
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, rate="2/m")

        @app.get("/api/test")
        def test_endpoint():
            return {"data": "ok"}

        client = TestClient(app)
        headers = {"X-Forwarded-For": "1.2.3.4"}
        assert client.get("/api/test", headers=headers).status_code == 200
        assert client.get("/api/test", headers=headers).status_code == 200
        assert client.get("/api/test", headers=headers).status_code == 429

    def test_different_ips_have_independent_limits(self, mock_redis_unavailable):
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, rate="2/m")

        @app.get("/api/test")
        def test_endpoint():
            return {"data": "ok"}

        client_a = TestClient(app, headers={"X-Forwarded-For": "1.1.1.1"})
        client_b = TestClient(app, headers={"X-Forwarded-For": "2.2.2.2"})

        assert client_a.get("/api/test").status_code == 200
        assert client_a.get("/api/test").status_code == 200
        assert client_a.get("/api/test").status_code == 429

        assert client_b.get("/api/test").status_code == 200
        assert client_b.get("/api/test").status_code == 200

    def test_static_path_exempt(self, mock_redis_unavailable):
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, rate="1/m")

        @app.get("/static/file.txt")
        def static_file():
            return {"file": "content"}

        client = TestClient(app)
        for _ in range(5):
            assert client.get("/static/file.txt").status_code == 200


class TestImageProxyExemption:
    """图片代理必须豁免限流。

    前端列表页一次加载数十张海报，且旧版 /img?url= 重定向与真实图片共用同一
    path，全站图片挤在同一限流键（api:{ip}:/img/）上必然触发限流。
    """

    def test_img_paths_bypass_limit(self, mock_redis_unavailable):
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, rate="1/m")

        @app.get("/img/")
        def img_redirect():
            return {"ok": True}

        @app.get("/img/tmdb/w500/poster.jpg")
        def img_file():
            return {"ok": True}

        client = TestClient(app)
        for _ in range(10):
            assert client.get("/img/").status_code == 200
            assert client.get("/img/tmdb/w500/poster.jpg").status_code == 200

    def test_other_api_still_limited(self, mock_redis_unavailable):
        """豁免 /img 不应顺带豁免普通 API"""
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, rate="1/m")

        @app.get("/api/other")
        def other():
            return {"ok": True}

        client = TestClient(app)
        assert client.get("/api/other").status_code == 200
        assert client.get("/api/other").status_code == 429


class TestRateLimitWarnThrottling:
    """同一限流键重复触发时只告警一次，其余降为 debug，避免刷屏"""

    def test_repeated_blocks_log_once(self, mock_redis_unavailable):
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, rate="1/m")

        @app.get("/api/spam")
        def spam():
            return {"ok": True}

        client = TestClient(app)
        assert client.get("/api/spam").status_code == 200
        warns = []
        debug_logs = []
        with patch(
            "app.infrastructure.rate_limiter.middleware.log"
        ) as mock_log:
            mock_log.warn.side_effect = lambda m: warns.append(m)
            mock_log.debug.side_effect = lambda m: debug_logs.append(m)
            for _ in range(5):
                assert client.get("/api/spam").status_code == 429

        assert len(warns) == 1, f"应只告警一次，实际 {len(warns)} 次"
        assert len(debug_logs) == 4
