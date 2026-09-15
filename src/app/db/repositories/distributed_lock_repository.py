"""
分布式锁 Repository
底层数据访问
"""

import time

from sqlalchemy import delete, update

import log
from app.db.models.distributed_lock import DISTRIBUTEDLOCK
from app.db.repositories.base_repository import BaseRepository


class DistributedLockRepository(BaseRepository):
    """分布式锁仓储"""

    def acquire(self, lock_key: str, token: str, instance: str, ttl_seconds: int) -> bool:
        """尝试获取锁：先抢占过期锁，再尝试插入新锁."""
        now = int(time.time())
        expires = now + ttl_seconds

        with self.session() as db:
            # 先尝试抢占已过期锁
            stmt = (
                update(DISTRIBUTEDLOCK)
                .where(
                    DISTRIBUTEDLOCK.LOCK_KEY == lock_key,
                    DISTRIBUTEDLOCK.EXPIRES_AT < now,
                )
                .values(TOKEN=token, INSTANCE=instance, EXPIRES_AT=expires)
            )
            result = db.execute(stmt)
            if result.rowcount > 0:
                db.commit()
                return True

            # 尝试插入新锁
            try:
                db.add(DISTRIBUTEDLOCK(LOCK_KEY=lock_key, TOKEN=token, INSTANCE=instance, EXPIRES_AT=expires))
                db.flush()
                db.commit()
                return True
            except Exception:
                db.rollback()
                return False

    def release(self, lock_key: str, token: str) -> bool:
        """释放锁（只有持有者才能释放）."""
        try:
            with self.session() as db:
                stmt = delete(DISTRIBUTEDLOCK).where(
                    DISTRIBUTEDLOCK.LOCK_KEY == lock_key,
                    DISTRIBUTEDLOCK.TOKEN == token,
                )
                result = db.execute(stmt)
                db.commit()
                return result.rowcount > 0
        except Exception as e:
            log.error(f"[DbLock]释放锁异常: {lock_key}, {e}")
            return False

    def extend(self, lock_key: str, token: str, additional_seconds: int) -> bool:
        """延长锁过期时间。

        语义与 Redis 实现（EXPIRE key N）保持一致：把过期时间设为「当前时间 + N」，
        而非在当前过期时间上累加。累加语义会让心跳续期不断推迟过期时间，进程退出后
        锁长时间不失效，阻塞后续重试。
        """
        try:
            expires = int(time.time()) + additional_seconds
            with self.session() as db:
                stmt = (
                    update(DISTRIBUTEDLOCK)
                    .where(
                        DISTRIBUTEDLOCK.LOCK_KEY == lock_key,
                        DISTRIBUTEDLOCK.TOKEN == token,
                    )
                    .values(EXPIRES_AT=expires)
                )
                result = db.execute(stmt)
                db.commit()
                return result.rowcount > 0
        except Exception as e:
            log.error(f"[DbLock]延长锁异常: {lock_key}, {e}")
            return False

    def get_by_key(self, lock_key: str) -> DISTRIBUTEDLOCK | None:
        """根据锁键获取记录."""
        with self.session() as db:
            return db.query(DISTRIBUTEDLOCK).filter(DISTRIBUTEDLOCK.LOCK_KEY == lock_key).first()
