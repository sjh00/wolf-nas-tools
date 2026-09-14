"""MessageGovernor 状态后端：内存（降级）与 Redis（多实例共享）.

窗口计数、去重标记、聚合缓冲集中在此层；Redis 后端用 Lua 保证原子性，
使多 worker/多实例下的治理判定一致。Redis 不可用时自动降级为进程内内存。
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from fnmatch import fnmatch
from typing import Any

import log
from app.infrastructure.redis.store import RedisStore


class GovernorStore(ABC):
    """治理层状态存储接口."""

    @abstractmethod
    def incr_window(self, key: str, ttl: int) -> int:
        """窗口计数 +1，首次设置 TTL，返回当前计数."""

    @abstractmethod
    def mark_dedup(self, key: str, ttl: int) -> bool:
        """标记去重键；若已存在返回 True（重复）."""

    @abstractmethod
    def append(self, key: str, item: str, ttl: int) -> None:
        """向聚合缓冲追加一条序列化明细."""

    @abstractmethod
    def drain(self, key: str) -> list[str]:
        """取出并清空聚合缓冲."""

    @abstractmethod
    def keys(self, pattern: str) -> list[str]:
        """按模式列出缓冲键."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """删除键."""


class MemoryGovernorStore(GovernorStore):
    """进程内状态（单 worker 或 Redis 不可用时降级）."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.RLock()
        self._window: dict[str, list] = {}
        self._dedup: dict[str, float] = {}
        self._lists: dict[str, list[str]] = {}

    def incr_window(self, key: str, ttl: int) -> int:
        now = self._clock()
        with self._lock:
            entry = self._window.get(key)
            if entry is None or entry[1] <= now:
                entry = [0, now + ttl]
                self._window[key] = entry
            entry[0] += 1
            return int(entry[0])

    def mark_dedup(self, key: str, ttl: int) -> bool:
        now = self._clock()
        with self._lock:
            expires = self._dedup.get(key)
            if expires is not None and expires > now:
                return True
            self._dedup[key] = now + ttl
            if len(self._dedup) > 8192:
                self._dedup = {k: v for k, v in self._dedup.items() if v > now}
            return False

    def append(self, key: str, item: str, ttl: int) -> None:
        with self._lock:
            self._lists.setdefault(key, []).append(item)

    def drain(self, key: str) -> list[str]:
        with self._lock:
            return list(self._lists.pop(key, []))

    def keys(self, pattern: str) -> list[str]:
        with self._lock:
            return [k for k in self._lists if fnmatch(k, pattern)]

    def delete(self, key: str) -> None:
        with self._lock:
            self._lists.pop(key, None)
            self._window.pop(key, None)
            self._dedup.pop(key, None)


class RedisGovernorStore(GovernorStore):
    """Redis 状态（多实例共享），关键操作用 Lua 保证原子性."""

    _LUA_WINDOW = "local c=redis.call('INCR',KEYS[1]); if c==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return c"
    _LUA_DEDUP = "if redis.call('SET',KEYS[1],'1','NX','EX',ARGV[1]) then return 0 else return 1 end"
    _LUA_DRAIN = "local v=redis.call('LRANGE',KEYS[1],0,-1); redis.call('DEL',KEYS[1]); return v"

    def __init__(self, store: RedisStore | None = None):
        self._store = store or RedisStore()
        self._shas: dict[str, str] = {}

    def _eval(self, name: str, script: str, numkeys: int, *args: Any) -> Any:
        sha = self._shas.get(name)
        if sha is None:
            sha = self._store.script_load(script)
            if sha is None:
                return None
            self._shas[name] = sha
        result = self._store.evalsha(sha, numkeys, *args)
        if result is None:
            # Redis 重启后脚本缓存丢失，重载一次
            self._shas.pop(name, None)
            sha = self._store.script_load(script)
            if sha is None:
                return None
            self._shas[name] = sha
            result = self._store.evalsha(sha, numkeys, *args)
        return result

    def incr_window(self, key: str, ttl: int) -> int:
        result = self._eval("window", self._LUA_WINDOW, 1, key, ttl)
        return int(result) if isinstance(result, int) else 0

    def mark_dedup(self, key: str, ttl: int) -> bool:
        result = self._eval("dedup", self._LUA_DEDUP, 1, key, ttl)
        return int(result) == 1 if isinstance(result, int) else False

    def append(self, key: str, item: str, ttl: int) -> None:
        self._store.rpush(key, item)
        self._store.expire(key, ttl)

    def drain(self, key: str) -> list[str]:
        result = self._eval("drain", self._LUA_DRAIN, 1, key)
        if not isinstance(result, list):
            return []
        return [v.decode("utf-8") if isinstance(v, bytes) else str(v) for v in result]

    def keys(self, pattern: str) -> list[str]:
        return self._store.keys(pattern)

    def delete(self, key: str) -> None:
        self._store.delete(key)


def build_governor_store() -> GovernorStore:
    """优先 Redis（多实例共享），不可用时降级为内存."""
    try:
        store = RedisStore()
        if store.is_available():
            return RedisGovernorStore(store)
    except Exception as e:  # noqa: BLE001
        log.warn(f"[MessageGovernor]Redis 状态后端不可用，降级内存: {e!s}")
    return MemoryGovernorStore()
