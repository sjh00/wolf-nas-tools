"""Agent Turn 与待确认动作 ORM 仓储。"""

from datetime import datetime, timedelta

from app.db.models.agent_memory import AGENTPENDINGACTION, AGENTTURN
from app.db.repositories.base_repository import BaseRepository


class AgentTurnRepository(BaseRepository):
    def create_turn(self, turn_id: str, user_id: str, session_id: str) -> AGENTTURN:
        with self.session() as db:
            row = AGENTTURN(ID=turn_id, USER_ID=user_id, SESSION_ID=session_id, STATUS="running")
            db.add(row)
            db.flush()
            return row

    def get_turn(self, turn_id: str) -> AGENTTURN | None:
        with self.session() as db:
            return db.query(AGENTTURN).filter(AGENTTURN.ID == turn_id).first()

    def set_status(self, turn_id: str, status: str) -> None:
        with self.session() as db:
            db.query(AGENTTURN).filter(AGENTTURN.ID == turn_id).update(
                {"STATUS": status, "UPDATED_AT": datetime.now()}, synchronize_session=False
            )

    def request_cancel(self, turn_id: str) -> None:
        with self.session() as db:
            db.query(AGENTTURN).filter(AGENTTURN.ID == turn_id).update(
                {"CANCEL_REQUESTED": True, "STATUS": "cancel_requested", "UPDATED_AT": datetime.now()},
                synchronize_session=False,
            )

    def create_pending(
        self,
        action_id: str,
        turn_id: str,
        user_id: str,
        tool: str,
        arguments: dict,
        message: str,
        ttl_seconds: int = 900,
    ) -> AGENTPENDINGACTION:
        with self.session() as db:
            row = AGENTPENDINGACTION(
                ID=action_id,
                TURN_ID=turn_id,
                USER_ID=user_id,
                TOOL=tool,
                ARGUMENTS=arguments,
                MESSAGE=message,
                STATUS="pending",
                EXPIRES_AT=datetime.now() + timedelta(seconds=ttl_seconds),
            )
            db.add(row)
            db.flush()
            return row

    def get_pending(self, action_id: str) -> AGENTPENDINGACTION | None:
        with self.session() as db:
            return db.query(AGENTPENDINGACTION).filter(AGENTPENDINGACTION.ID == action_id).first()

    def set_pending_status(self, action_id: str, status: str) -> None:
        with self.session() as db:
            db.query(AGENTPENDINGACTION).filter(AGENTPENDINGACTION.ID == action_id).update(
                {"STATUS": status}, synchronize_session=False
            )
