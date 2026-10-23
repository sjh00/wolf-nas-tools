"""Provider 错误语义.

业务层只依赖这些类型做降级判断，不依赖具体 provider 的异常。
"""

from __future__ import annotations


class ProviderError(Exception):
    """所有 provider 错误的基类."""

    retryable = False

    def __init__(self, provider: str, message: str = "") -> None:
        self.provider = provider
        self.message = message
        super().__init__(f"[{provider}] {message}" if message else f"[{provider}] provider error")


class ProviderNotFound(ProviderError):
    """条目不存在（可缓存短时空结果）."""


class ProviderTimeout(ProviderError):
    retryable = True


class ProviderUnavailable(ProviderError):
    retryable = True


class ProviderRateLimited(ProviderError):
    retryable = True


class ProviderAuthError(ProviderError):
    """Cookie/Token 失效，需要用户重新配置."""


class ProviderParseError(ProviderError):
    """页面/响应结构变化，需告警."""


class ProviderSchemaError(ProviderError):
    """返回 DTO 不符合声明的 schema_version."""
