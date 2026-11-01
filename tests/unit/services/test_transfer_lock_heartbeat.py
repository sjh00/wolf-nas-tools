"""文件转移锁心跳：长时间转移续期，释放后停止."""

import time
from dataclasses import dataclass

from app.services.transfer.filetransfer_service import FileTransferService


@dataclass
class _FakeLock:
    owned: bool = True
    extends: int = 0

    def extend(self, _ttl: int) -> bool:
        self.extends += 1
        return self.owned


def test_heartbeat_extends_lock_while_owned():
    lock = _FakeLock()
    thread = FileTransferService._start_lock_heartbeat(lock, ttl_seconds=60, interval=0.01)
    time.sleep(0.05)
    lock.owned = False
    thread.join(timeout=1)

    assert lock.extends >= 1
    assert not thread.is_alive()
