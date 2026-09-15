"""FastAPI 速率限制中间件."""

import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

import log
from app.infrastructure.rate_limiter import RateLimitEngine


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    全局 API 速率限制中间件

    基于客户端 IP 的令牌桶限流，Redis 可用时分布式生效，
    否则降级为单进程内存限流。

    豁免路径：
    - /health  健康检查
    - /static  静态文件
    - /img     图片代理（前端列表页一次加载数十张海报，且旧版 /img?url= 重定向
               与真实图片共用同一 path，全站图片挤在同一限流键上必然超限）
    - /docs /openapi.json  Swagger
    """

    _EXEMPT_PATHS = {"/health", "/static", "/img", "/docs", "/openapi.json", "/redoc"}

    # 特定路径自定义限流规则：{path: rate}
    _PATH_LIMITS: dict[str, str] = {
        "/api/system/refresh": "30/m",
        "/api/auth/login": "5/m",
        "/api/agent/chat": "20/m",
        "/api/agent/chat/confirm": "20/m",
        "/api/agent/message/interact": "10/m",
        "/api/agent/message/stream": "10/m",
    }

    # 同一限流键的告警抑制窗口（秒）
    _WARN_SUPPRESS_SECONDS = 60

    def __init__(self, app, rate: str = "60/m"):
        super().__init__(app)
        self._engine = RateLimitEngine()
        self._rate = rate
        # {限流键: 上次告警时间}，用于抑制重复告警刷屏
        self._warned_at: dict[str, float] = {}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 豁免路径
        if any(path.startswith(exempt) for exempt in self._EXEMPT_PATHS):
            return await call_next(request)

        # 提取客户端 IP
        client_ip = self._get_client_ip(request)
        key = f"api:{client_ip}:{path}"

        # 特定路径使用自定义限流，其余使用全局默认值
        rate = self._PATH_LIMITS.get(path, self._rate)

        if not self._engine.try_acquire(key, rate=rate):
            self._log_throttled(client_ip, path, key)
            return JSONResponse(
                content={"detail": "请求过于频繁，请稍后再试"},
                status_code=429,
            )

        return await call_next(request)

    def _log_throttled(self, client_ip: str, path: str, key: str) -> None:
        """同一限流键在窗口内只告警一次，其余降为 debug，避免触发时刷屏"""
        now = time.time()
        last = self._warned_at.get(key, 0.0)
        if now - last >= self._WARN_SUPPRESS_SECONDS:
            self._warned_at[key] = now
            log.warn(f"[RateLimit]IP {client_ip} 请求 {path} 触发限流")
        else:
            log.debug(
                f"[RateLimit]IP {client_ip} 请求 {path} 触发限流"
                f"（{self._WARN_SUPPRESS_SECONDS}s 内重复触发，已抑制）"
            )
        # 防止键无限累积
        if len(self._warned_at) > 1000:
            cutoff = now - self._WARN_SUPPRESS_SECONDS
            self._warned_at = {k: v for k, v in self._warned_at.items() if v >= cutoff}

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        """获取真实客户端 IP"""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-Ip")
        if real_ip:
            return real_ip.strip()
        return request.client.host if request.client else "unknown"
