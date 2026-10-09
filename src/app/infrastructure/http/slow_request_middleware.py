"""慢请求日志中间件（纯 ASGI）.

测量每个 HTTP 请求耗时，超过阈值（默认 1000ms）时告警，便于定位间歇性变慢/超时的真实卡点。
纯 ASGI 实现，不阻塞事件循环。
"""

import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

import log


class SlowRequestLoggingMiddleware:
    """记录超过阈值的慢请求：method / path / 状态码 / 耗时 / 客户端 IP."""

    def __init__(self, app: ASGIApp, slow_ms: float = 1000.0):
        self.app = app
        self._slow_ms = float(slow_ms)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status = 0

        async def _send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message.get("status", 0)
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            if duration_ms >= self._slow_ms:
                method = scope.get("method", "")
                path = scope.get("path", "")
                client = scope.get("client")
                client_ip = client[0] if client else "-"
                log.warn(f"[SlowRequest] {method} {path} -> {status} {duration_ms:.0f}ms client={client_ip}")
