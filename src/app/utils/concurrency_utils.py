"""并发工具：实例级互斥锁与同步装饰器。

用于为“持有会话、非线程安全”的对象（如下载器客户端 qbittorrentapi.Client /
transmission-rpc）提供**每实例可重入锁**，避免多线程并发访问同一实例导致
会话被并发重建（表现为“登录成功却 403”、任务卡死）。

设计：
- 锁惰性创建并挂在对象 `__dict__` 上，无需子类调用 super().__init__；
- 可重入（RLock），同一线程内嵌套调用不会自锁；
- 创建过程加全局锁，保证并发首次访问安全。
"""

import functools
import threading
from collections.abc import Callable
from typing import Any, TypeVar, cast

_F = TypeVar("_F", bound=Callable[..., Any])

_create_lock = threading.Lock()


class ConcurrencyUtils:
    """并发相关工具方法集合。"""

    @staticmethod
    def get_instance_lock(obj: Any, name: str = "_api_lock") -> threading.RLock:
        """返回对象的每实例可重入锁（惰性创建，线程安全）。"""
        lock = obj.__dict__.get(name)
        if lock is None:
            with _create_lock:
                lock = obj.__dict__.get(name)
                if lock is None:
                    lock = threading.RLock()
                    obj.__dict__[name] = lock
        return lock

    @staticmethod
    def synchronized(func: _F) -> _F:
        """方法级同步装饰器：以 `self` 的每实例锁串行化调用（同线程可重入）。"""

        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            with ConcurrencyUtils.get_instance_lock(self):
                return func(self, *args, **kwargs)

        return cast(_F, wrapper)
