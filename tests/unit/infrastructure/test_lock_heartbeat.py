"""锁续期心跳与 extend 语义。

背景：媒体转移锁原先 TTL=3600s 且无续期。进程意外退出（重启/卡死）后，残留锁会把
该路径的转移整整挡住一小时（表现为"什么都没在转移，却一直提示正在其他实例转移中"）。
改为「短 TTL + 心跳续期」后：任务存活期间锁不过期，进程一退出锁在 TTL 内失效。
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from app.infrastructure.distributed_lock import heartbeat as hb_module
from app.infrastructure.distributed_lock.heartbeat import lock_heartbeat


class TestLockHeartbeat:
    def test_stops_extending_after_exit(self):
        """心跳必须在 with 退出后停止，否则线程泄漏且锁永不失效"""
        lock = MagicMock()
        with lock_heartbeat(lock, ttl_seconds=15):
            pass
        calls_after_exit = lock.extend.call_count
        time.sleep(0.3)
        assert lock.extend.call_count == calls_after_exit

    def test_extend_failure_does_not_raise(self):
        """续期失败不能打断业务：锁到期后自然失效，由下一轮重试"""
        lock = MagicMock()
        lock.extend.side_effect = RuntimeError("db down")
        with lock_heartbeat(lock, ttl_seconds=15):
            time.sleep(0.1)
        # 未抛出即通过

    def test_interval_has_minimum(self):
        """TTL 极小时间隔不得退化为 0，避免疯狂打数据库"""
        lock = MagicMock()
        with lock_heartbeat(lock, ttl_seconds=1):
            time.sleep(0.05)
        assert hb_module._MIN_INTERVAL_SECONDS >= 5


class TestDbLockExtendSemantics:
    """DB 的 extend 必须与 Redis（EXPIRE key N）一致：设为 now+N，而非累加。"""

    KEY = "lab:test:extend-semantics"

    @pytest.fixture(autouse=True)
    def _ensure_tables(self):
        # 测试库为 conftest 指定的临时 sqlite，未跑迁移，需先建表
        from app.db.session import Database

        Database().create_all()
        yield

    def _expires_at(self, repo) -> int:
        from app.db.models.distributed_lock import DISTRIBUTEDLOCK

        with repo.session() as db:
            row = db.query(DISTRIBUTEDLOCK).filter(DISTRIBUTEDLOCK.LOCK_KEY == self.KEY).first()
            assert row is not None
            return int(row.EXPIRES_AT)

    def test_extend_sets_absolute_expiry_not_accumulate(self):
        from app.db.repositories.distributed_lock_repository import DistributedLockRepository

        repo = DistributedLockRepository()
        repo.release(self.KEY, "tok")
        try:
            assert repo.acquire(lock_key=self.KEY, token="tok", instance="lab", ttl_seconds=200) is True
            before = self._expires_at(repo)

            # 连续两次续期同样的秒数：绝对语义下到期时间几乎不变；
            # 累加语义下会被推远约 2×N（正是导致残留锁长期不失效的原因）
            assert repo.extend(self.KEY, "tok", 200) is True
            assert repo.extend(self.KEY, "tok", 200) is True
            after = self._expires_at(repo)

            assert abs(after - before) <= 3, f"extend 应为绝对设置，实际推远了 {after - before}s（累加语义）"
        finally:
            repo.release(self.KEY, "tok")

    def test_extend_requires_matching_token(self):
        """非持有者不能续期"""
        from app.db.repositories.distributed_lock_repository import DistributedLockRepository

        repo = DistributedLockRepository()
        repo.release(self.KEY, "tok")
        try:
            assert repo.acquire(lock_key=self.KEY, token="tok", instance="lab", ttl_seconds=200) is True
            assert repo.extend(self.KEY, "other-token", 200) is False
        finally:
            repo.release(self.KEY, "tok")
