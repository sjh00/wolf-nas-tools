"""ConcurrencyUtils：每实例同步装饰器与惰性锁。"""

import threading
import time

from app.utils import ConcurrencyUtils


class _Obj:
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self._guard = threading.Lock()

    @ConcurrencyUtils.synchronized
    def work(self, sleep: float = 0.02) -> None:
        with self._guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(sleep)
        with self._guard:
            self.active -= 1


def test_synchronized_serializes_per_instance():
    obj = _Obj()
    threads = [threading.Thread(target=obj.work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert obj.max_active == 1


def test_instance_locks_isolated_and_reused():
    a, b = _Obj(), _Obj()
    la = ConcurrencyUtils.get_instance_lock(a)
    assert la is ConcurrencyUtils.get_instance_lock(a)
    assert la is not ConcurrencyUtils.get_instance_lock(b)
