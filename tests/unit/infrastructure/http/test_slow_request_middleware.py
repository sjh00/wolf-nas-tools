"""慢请求日志中间件测试."""

from fastapi import FastAPI
from starlette.responses import StreamingResponse
from starlette.testclient import TestClient

from app.infrastructure.http.slow_request_middleware import SlowRequestLoggingMiddleware


def _make_app(slow_ms: float) -> TestClient:
    app = FastAPI()
    app.add_middleware(SlowRequestLoggingMiddleware, slow_ms=slow_ms)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return TestClient(app)


def test_slow_request_logged(monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr("app.infrastructure.http.slow_request_middleware.log.warn", lambda msg: warnings.append(msg))

    client = _make_app(slow_ms=0)  # 任何请求都视为慢
    assert client.get("/ping").status_code == 200
    assert any("[SlowRequest]" in m for m in warnings)


def test_fast_request_not_logged(monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr("app.infrastructure.http.slow_request_middleware.log.warn", lambda msg: warnings.append(msg))

    client = _make_app(slow_ms=1e9)  # 阈值极大，不应记录
    assert client.get("/ping").status_code == 200
    assert warnings == []


def test_sse_stream_not_logged(monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr("app.infrastructure.http.slow_request_middleware.log.warn", lambda msg: warnings.append(msg))

    app = FastAPI()
    app.add_middleware(SlowRequestLoggingMiddleware, slow_ms=0)  # 任何请求都视为慢

    @app.get("/api/agent/message/stream")
    def stream():
        return StreamingResponse(iter([b"data: 1\n\n"]), media_type="text/event-stream")

    assert TestClient(app).get("/api/agent/message/stream").status_code == 200
    assert warnings == []  # SSE 长连接不告警
