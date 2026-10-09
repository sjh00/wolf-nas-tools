"""FastAPI 速率限制中间件（纯 ASGI 实现）."""

import json

from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

import log
from app.infrastructure.rate_limiter import RateLimitEngine


class RateLimitMiddleware:
    """
    全局 API 速率限制中间件

    基于客户端 IP 的令牌桶限流，Redis 可用时分布式生效，
    否则降级为单进程内存限流。

    实现为**纯 ASGI 中间件**（非 BaseHTTPMiddleware），并把限流判定放到工作线程执行：
    限流后端（Redis）是同步阻塞 I/O，若直接在 asyncio 事件循环里调用，Redis 抖动时
    会阻塞整个 worker，导致全站 API 间歇性超时。

    豁免路径：
    - /health  健康检查
    - /static  静态文件
    - /docs /openapi.json  Swagger
    """

    _EXEMPT_PATHS = ("/health", "/static", "/docs", "/openapi.json", "/redoc")

    # 特定路径自定义限流规则：{path: rate}
    _PATH_LIMITS: dict[str, str] = {
        "/api/system/refresh": "30/m",
        "/api/auth/login": "5/m",
        "/api/agent/chat": "20/m",
        "/api/agent/chat/confirm": "20/m",
        "/api/agent/message/interact": "10/m",
        "/api/agent/message/stream": "10/m",
    }

    def __init__(self, app: ASGIApp, rate: str = "60/m"):
        self.app = app
        self._engine = RateLimitEngine()
        self._rate = rate

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "") or ""

        # 豁免路径
        if path.startswith(self._EXEMPT_PATHS):
            await self.app(scope, receive, send)
            return

        client_ip = self._get_client_ip(scope)
        key = f"api:{client_ip}:{path}"
        rate = self._PATH_LIMITS.get(path, self._rate)

        # 限流后端为同步阻塞调用，放到线程池避免阻塞事件循环
        allowed = await run_in_threadpool(self._engine.try_acquire, key, rate)
        if not allowed:
            log.warn(f"[RateLimit]IP {client_ip} 请求 {path} 触发限流")
            await self._send_429(send)
            return

        await self.app(scope, receive, send)

    @staticmethod
    def _get_client_ip(scope: Scope) -> str:
        """获取真实客户端 IP"""
        forwarded = ""
        real_ip = ""
        for key, value in scope.get("headers") or []:
            lkey = key.lower()
            if lkey == b"x-forwarded-for":
                forwarded = value.decode("latin-1")
            elif lkey == b"x-real-ip":
                real_ip = value.decode("latin-1")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if real_ip:
            return real_ip.strip()
        client = scope.get("client")
        return client[0] if client else "unknown"

    @staticmethod
    async def _send_429(send: Send) -> None:
        body = json.dumps({"detail": "请求过于频繁，请稍后再试"}, ensure_ascii=False).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
