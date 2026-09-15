"""分布式锁续期心跳。

长任务（大文件转移、整库索引重建）可能超过锁 TTL。若把 TTL 设得很长，
进程崩溃/被重启后锁会长时间残留，把后续重试全部挡在门外（表现为"什么都没在转移，
却一直提示正在其他实例转移中"）；若把 TTL 设得很短，长任务又会中途过期，
另一实例可并发进入造成重复转移。

心跳 + 短 TTL 同时解决两者：任务存活期间持续续期，进程一旦退出，锁在 TTL 内自然失效。
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

import log

# 心跳间隔下限（秒）：避免 TTL 过小时过于频繁地打数据库
_MIN_INTERVAL_SECONDS = 5


@contextmanager
def lock_heartbeat(lock, ttl_seconds: int) -> Iterator[None]:
    """持有锁期间在后台定期续期。

    :param lock: 已成功 acquire 的 DistributedLock
    :param ttl_seconds: 与 acquire 时一致的锁 TTL，续期时按此值重置过期时间
    """
    interval = max(_MIN_INTERVAL_SECONDS, ttl_seconds // 3)
    stop_event = threading.Event()

    def _beat() -> None:
        # wait 返回 True 表示收到停止信号，直接退出，避免多余的一次续期
        while not stop_event.wait(interval):
            try:
                lock.extend(ttl_seconds)
            except Exception as e:  # noqa: BLE001
                # 续期失败不中断业务：锁到期后自然失效，任务会由下一轮重试
                log.debug(f"[Lock]锁续期失败（到期后将自动释放）: {e}")

    thread = threading.Thread(target=_beat, name="lock-heartbeat", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop_event.set()
