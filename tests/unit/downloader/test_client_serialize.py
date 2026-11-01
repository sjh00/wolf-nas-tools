"""下载器客户端并发安全：每个实例的公开方法应被串行化（每实例可重入锁）。

背景：客户端内部持有登录会话，非线程安全；多任务并发调用同一实例会导致
会话被并发重建（“登录成功却 403”）。基类元类为每实例公开方法加锁。
"""

import threading
import time

from app.downloader.client._base import _IDownloadClient

_Meta = type(_IDownloadClient)


class _Dummy(metaclass=_Meta):
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self._guard = threading.Lock()

    def work(self, sleep: float = 0.02) -> None:
        with self._guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(sleep)
        with self._guard:
            self.active -= 1


def test_public_methods_serialized_per_instance():
    d = _Dummy()
    threads = [threading.Thread(target=d.work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert d.max_active == 1


def test_locks_isolated_between_instances():
    a, b = _Dummy(), _Dummy()
    a.work(0)
    b.work(0)
    assert getattr(a, "_api_lock") is not getattr(b, "_api_lock")
