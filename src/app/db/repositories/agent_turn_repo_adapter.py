"""Agent Turn 与待确认动作领域仓储适配器。"""

from app.db.repositories.agent_turn_repository import AgentTurnRepository
from app.domain.entities.agent_turn import AgentTurnEntity, PendingActionEntity


class AgentTurnRepositoryAdapter:
    def __init__(self, repo: AgentTurnRepository | None = None):
        self._repo = repo or AgentTurnRepository()

    def create_turn(self, turn_id: str, user_id: str, session_id: str) -> AgentTurnEntity:
        return AgentTurnEntity.from_orm(self._repo.create_turn(turn_id, user_id, session_id))

    def get_turn(self, turn_id: str) -> AgentTurnEntity | None:
        row = self._repo.get_turn(turn_id)
        return AgentTurnEntity.from_orm(row) if row is not None else None

    def set_status(self, turn_id: str, status: str) -> None:
        self._repo.set_status(turn_id, status)

    def request_cancel(self, turn_id: str) -> None:
        self._repo.request_cancel(turn_id)

    def create_pending(
        self,
        action_id: str,
        turn_id: str,
        user_id: str,
        tool: str,
        arguments: dict,
        message: str,
    ) -> PendingActionEntity:
        row = self._repo.create_pending(action_id, turn_id, user_id, tool, arguments, message)
        return PendingActionEntity.from_orm(row)

    def get_pending(self, action_id: str) -> PendingActionEntity | None:
        row = self._repo.get_pending(action_id)
        return PendingActionEntity.from_orm(row) if row is not None else None

    def set_pending_status(self, action_id: str, status: str) -> None:
        self._repo.set_pending_status(action_id, status)
