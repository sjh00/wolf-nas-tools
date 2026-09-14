"""HTTP 认证工具."""

from typing import Any

import httpx2


class CookieAuth(httpx2.Auth):
    """Cookie 认证（兼容 httpx2.Auth）.

    auth_flow 只在原始请求注入 Cookie header；httpx2 跨重定向会 pop Cookie header
    （httpx 假设 cookie 由 client.cookies jar 管理）。HttpClient.request 在收到 CookieAuth
    时会自动同步写入 client.cookies jar，确保 302 后 cookie 仍生效（PT 站场景）。
    """

    def __init__(self, cookies: dict[str, str] | str | None = None):
        self._cookies = self._parse_cookies(cookies)

    @property
    def cookies(self) -> dict[str, str]:
        """供 HttpClient 写入 client.cookies jar，重定向时自动保留 cookie"""
        return dict(self._cookies)

    @staticmethod
    def _parse_cookies(cookies: dict[str, str] | str | None) -> dict[str, str]:
        if cookies is None:
            return {}
        if isinstance(cookies, dict):
            return cookies
        result = {}
        for part in str(cookies).split(";"):
            part = part.strip()
            if "=" in part:
                key, value = part.split("=", 1)
                result[key.strip()] = value.strip()
        return result

    def auth_flow(self, request: httpx2.Request) -> Any:
        if self._cookies:
            cookie_str = "; ".join(f"{k}={v}" for k, v in self._cookies.items())
            request.headers["Cookie"] = cookie_str
        yield request

    def apply(self, request: httpx2.Request) -> httpx2.Request:
        """直接修改 request（兼容旧用法）."""
        if self._cookies:
            cookie_str = "; ".join(f"{k}={v}" for k, v in self._cookies.items())
            request.headers["Cookie"] = cookie_str
        return request


class BearerAuth(httpx2.Auth):
    """Bearer Token 认证."""

    def __init__(self, token: str):
        self._token = token

    def auth_flow(self, request: httpx2.Request) -> Any:
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request


class ApiKeyAuth(httpx2.Auth):
    """API Key 认证（支持 header 或 query 参数）."""

    def __init__(self, key: str, value: str, location: str = "header"):
        self._key = key
        self._value = value
        self._location = location

    def auth_flow(self, request: httpx2.Request) -> Any:
        if self._location == "header":
            request.headers[self._key] = self._value
        elif self._location == "query":
            request.url = request.url.copy_merge_params({self._key: self._value})
        yield request
