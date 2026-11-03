"""Site rate limiter service — 站点限流服务.

替换旧的 app/sites/site_limiter.py，使用 RateLimitEngine 统一限流框架.

**最低间隔兜底**：多数 PT 站点在站点规则里写明「两次请求间隔不得小于 N 秒」
（HDSky 等为 60 秒），超频会被临时限制甚至封禁。站点 NOTE 里的 rate_limit 是
人工配置，容易漏改或沿用旧值（历史上统一是 10/m，比 60 秒 1 次快 10 倍），
因此这里对生效速率做硬性下限：折算出的单次间隔不足 ``min_interval_seconds``
时一律拉高，burst 同步压到 1，避免「速率合规但突发连发」绕过间隔限制。
"""

import json
import threading

import log
from app.infrastructure.rate_limiter import RateLimitEngine
from app.infrastructure.rate_limiter.backends import _parse_rate
from app.utils.json_utils import JsonUtils

# 站点请求最小间隔（秒）。PT 站普遍要求 60 秒/次，且 RSS 之外的页面访问更容易触发风控。
DEFAULT_MIN_INTERVAL_SECONDS = 60


class SiteRateLimiterService:
    """站点限流服务 — 按站点 ID 管理限流."""

    def __init__(self, engine: RateLimitEngine | None = None, min_interval_seconds: int = DEFAULT_MIN_INTERVAL_SECONDS):
        self._engine = engine or RateLimitEngine()
        self._site_rates: dict[str, tuple[str, int]] = {}
        self._cfg_burst: dict[str, int] = {}
        self._lock = threading.Lock()
        # 硬下限：任何站点的实际请求间隔不得小于该值（<=0 表示关闭兜底）
        self._min_interval = int(min_interval_seconds)

    def _apply_min_interval(self, site_id: str, rate_str: str, burst: int) -> tuple[str, int, bool]:
        """把配置速率钳制到不低于最小间隔，返回 (rate, burst, 是否被钳制)。"""
        if self._min_interval <= 0:
            return rate_str, burst, False
        try:
            count, window = _parse_rate(rate_str)
        except ValueError:
            # 无法解析的配置按「1 次/最小间隔」处理，宁可慢也不触发风控
            return f"1/{self._min_interval}s", 1, True
        if count <= 0:
            return f"1/{self._min_interval}s", 1, True
        interval = window / count
        if interval >= self._min_interval:
            return rate_str, burst, False
        clamped = f"1/{self._min_interval}s"
        # burst=1：速率合规但允许突发 N 个请求，仍会瞬间连发触发风控
        return clamped, 1, True

    def register_site(self, site_id: str, site_note: str | dict | None) -> None:
        """注册站点限流配置.

        支持新旧两种配置格式：
        - 旧: {"limit_interval": 60, "limit_count": 10, "limit_seconds": 10}
        - 新: {"rate_limit": "10/m", "rate_burst": 10}
        """
        note = site_note if isinstance(site_note, dict) else {}
        if isinstance(site_note, str):
            try:
                note = JsonUtils.loads(site_note)
            except json.JSONDecodeError:
                note = {}

        # 优先使用新配置格式
        rate_str = note.get("rate_limit")
        burst = note.get("rate_burst")

        if rate_str:
            rate_str = str(rate_str)
        if burst is not None:
            burst = int(burst)

        if not rate_str:
            # 兼容旧配置格式
            limit_interval = note.get("limit_interval")
            limit_count = note.get("limit_count")
            limit_seconds = note.get("limit_seconds")

            # 站点配置可能以字符串形式存储，统一转换为数值
            try:
                limit_interval = int(limit_interval) if limit_interval is not None else None
            except (ValueError, TypeError):
                limit_interval = None
            try:
                limit_count = int(limit_count) if limit_count is not None else None
            except (ValueError, TypeError):
                limit_count = None
            try:
                limit_seconds = int(limit_seconds) if limit_seconds is not None else None
            except (ValueError, TypeError):
                limit_seconds = None

            if limit_interval and limit_count:
                # 转换为 rate 格式
                rate_str = f"{limit_count}/{limit_interval}s"
                if burst is None:
                    burst = int(limit_count)
            elif limit_seconds:
                # 只有访问间隔限制，转换为 rate
                rate_str = f"1/{limit_seconds}s"
                if burst is None:
                    burst = 1

        if not rate_str:
            # 未配置任何速率：按最小间隔兜底，而不是「不限流」。
            # 早期实现直接 pop 掉站点 → 完全不受限，一旦某站点漏配就是裸奔访问。
            if self._min_interval > 0:
                with self._lock:
                    self._site_rates[site_id] = (f"1/{self._min_interval}s", 1)
                    self._cfg_burst[site_id] = 1
            else:
                with self._lock:
                    self._site_rates.pop(site_id, None)
            return

        if burst is None:
            # 默认 burst 等于 rate 的 count
            try:
                count = float(rate_str.split("/")[0])
                burst = int(count)
            except (ValueError, IndexError):
                burst = 10

        burst = max(1, int(burst))
        rate_str, burst, clamped = self._apply_min_interval(site_id, rate_str, burst)

        with self._lock:
            self._site_rates[site_id] = (rate_str, burst)
            self._cfg_burst[site_id] = burst
        if clamped:
            log.info(
                f"[SiteRateLimit]站点 {site_id} 速率低于最小间隔 "
                f"{self._min_interval}s，已钳制为 {rate_str} burst={burst}"
            )

    def check(self, site_id: str, timeout: float | None = 0) -> bool:
        """检查站点是否触发流控.

        :param site_id: 站点 ID
        :param timeout: 等待秒数，0=立即返回，None=不等待直接返回 False
        :return: True=触发了流控（未获得许可），False=未触发
        """
        with self._lock:
            config = self._site_rates.get(site_id)
        if not config:
            return False

        rate_str, burst = config
        key = f"site:{site_id}"
        acquired = self._engine.acquire(key, rate=rate_str, burst=burst, timeout=timeout)
        return not acquired

    @property
    def engine(self) -> RateLimitEngine:
        """暴露底层限流引擎，供 HttpClient 注入使用."""
        return self._engine

    def get_rate(self, site_id: str) -> tuple[str, int] | None:
        """获取站点限流配置.

        :return: (rate_str, burst) 或 None（未配置限流）
        """
        with self._lock:
            return self._site_rates.get(site_id)

    def get_status(self, site_id: str | None = None) -> dict:
        """获取站点限流状态."""
        if site_id:
            key = f"site:{site_id}"
            return self._engine.get_status(key)
        return self._engine.get_status()
