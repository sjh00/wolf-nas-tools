"""图片代理 Referer 注册表.

插件通过 manifest 声明 host 后缀 -> Referer；核心只做通用匹配，不包含站点名。
"""

from __future__ import annotations

from threading import RLock
from urllib.parse import urlparse

import log


class ImageRefererRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._entries: dict[str, tuple[str, str]] = {}

    def register_pack(self, plugin_id: str, rules: dict | None) -> None:
        if not isinstance(rules, dict):
            return
        with self._lock:
            for host, referer in rules.items():
                host_key = str(host or "").strip().lower()
                ref = str(referer or "").strip()
                if not host_key or not ref:
                    continue
                if host_key in self._entries and self._entries[host_key][0] != plugin_id:
                    log.warn(f"[ImageProxy]Referer 冲突，保留已注册规则: {host_key}")
                    continue
                self._entries[host_key] = (plugin_id, ref)

    def unregister_plugin(self, plugin_id: str) -> None:
        with self._lock:
            for host, (owner, _ref) in list(self._entries.items()):
                if owner == plugin_id:
                    self._entries.pop(host, None)

    def resolve(self, url: str) -> str | None:
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return None
        with self._lock:
            for suffix, (_owner, referer) in self._entries.items():
                if host == suffix or host.endswith("." + suffix):
                    return referer
        return None


image_referer_registry = ImageRefererRegistry()
# 核心自带来源的 Referer 规则；插件规则仍由 manifest 注入。
image_referer_registry.register_pack(
    "builtin",
    {
        "doubanio.com": "https://movie.douban.com/",
        "douban.com": "https://movie.douban.com/",
        "bgm.tv": "https://bangumi.tv/",
    },
)
