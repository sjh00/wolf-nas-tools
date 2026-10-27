"""Agent Turn 生命周期、协作式取消与待确认动作管理。"""

import threading
import uuid
from datetime import datetime
from typing import Any

from app.db.repositories.agent_turn_repo_adapter import AgentTurnRepositoryAdapter
from app.domain.entities.agent_turn import PendingActionEntity
from app.infrastructure.distributed_lock import get_lock_manager


class AgentBusyError(RuntimeError):
    pass


class AgentCancelledError(RuntimeError):
    pass


class AgentConfirmError(RuntimeError):
    pass


class AgentRuntime:
    """按会话串行执行 Turn，并持久化危险确认动作。"""

    def __init__(self, repo: AgentTurnRepositoryAdapter | None = None):
        self._repo = repo or AgentTurnRepositoryAdapter()
        self._lock = threading.Lock()
        self._active: dict[str, tuple[str, threading.Event]] = {}
        self._turns: dict[str, threading.Event] = {}
        self._session_locks: dict[str, Any] = {}

    def start_turn(self, session_id: str, user_id: str) -> str:
        with self._lock:
            if session_id in self._active:
                raise AgentBusyError("当前会话仍有进行中的请求")
            turn_id = uuid.uuid4().hex
            event = threading.Event()
            self._active[session_id] = (turn_id, event)
            self._turns[turn_id] = event
        dist_lock = get_lock_manager().create_lock(f"agent:session:{session_id}", ttl_seconds=900)
        if not dist_lock.acquire():
            with self._lock:
                self._active.pop(session_id, None)
                self._turns.pop(turn_id, None)
            raise AgentBusyError("当前会话仍有进行中的请求")
        self._session_locks[session_id] = dist_lock
        try:
            self._repo.create_turn(turn_id, user_id, session_id)
        except Exception:
            dist_lock.release()
            with self._lock:
                self._active.pop(session_id, None)
                self._turns.pop(turn_id, None)
                self._session_locks.pop(session_id, None)
            raise
        return turn_id

    def finish_turn(self, turn_id: str, status: str, session_id: str) -> None:
        self._repo.set_status(turn_id, status)
        if status in ("completed", "failed", "cancelled"):
            with self._lock:
                active = self._active.get(session_id)
                if active and active[0] == turn_id:
                    self._active.pop(session_id, None)
                self._turns.pop(turn_id, None)
                dist_lock = self._session_locks.pop(session_id, None)
                if dist_lock and hasattr(dist_lock, "release"):
                    dist_lock.release()

    def get_turn(self, turn_id: str):
        return self._repo.get_turn(turn_id)

    def cancel_turn(self, turn_id: str, user_id: str) -> None:
        turn = self._repo.get_turn(turn_id)
        if turn is None or turn.user_id != user_id:
            raise AgentConfirmError("请求不存在或无权取消")
        with self._lock:
            event = self._turns.get(turn_id)
            if event:
                event.set()
        self._repo.request_cancel(turn_id)

    def should_cancel(self, turn_id: str) -> bool:
        with self._lock:
            event = self._turns.get(turn_id)
            if event and event.is_set():
                return True
        turn = self._repo.get_turn(turn_id)
        return bool(turn and turn.cancel_requested)

    def cancel_session(self, session_id: str, user_id: str) -> None:
        with self._lock:
            active = self._active.get(session_id)
        if active:
            self.cancel_turn(active[0], user_id)

    def create_pending(
        self,
        turn_id: str,
        tool: str,
        arguments: dict,
        message: str,
        user_id: str,
        session_id: str,
    ) -> PendingActionEntity:
        turn = self._repo.get_turn(turn_id)
        if turn is None or turn.user_id != user_id or turn.session_id != session_id:
            raise AgentConfirmError("无法创建确认动作")
        action = self._repo.create_pending(uuid.uuid4().hex, turn_id, user_id, tool, arguments, message)
        self._repo.set_status(turn_id, "awaiting_confirmation")
        return action

    def get_pending(self, action_id: str, user_id: str) -> PendingActionEntity:
        action = self._repo.get_pending(action_id)
        if action is None or action.user_id != user_id:
            raise AgentConfirmError("确认动作不存在或已失效")
        if action.status != "pending":
            raise AgentConfirmError("确认动作已处理")
        if action.expires_at < datetime.now():
            raise AgentConfirmError("确认动作已过期，请重新发起请求")
        return action

    def complete_pending(self, action_id: str, turn_id: str, status: str, session_id: str) -> None:
        self._repo.set_pending_status(action_id, status)
        self.finish_turn(turn_id=turn_id, status="completed", session_id=session_id)
