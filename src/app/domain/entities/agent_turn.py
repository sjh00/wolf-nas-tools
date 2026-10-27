"""Agent Turn 与待确认动作领域实体。"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class AgentTurnEntity:
    id: str
    user_id: str
    session_id: str
    status: str
    cancel_requested: bool = False

    @classmethod
    def from_orm(cls, row) -> "AgentTurnEntity":
        return cls(
            id=row.ID,
            user_id=row.USER_ID,
            session_id=row.SESSION_ID,
            status=row.STATUS,
            cancel_requested=bool(row.CANCEL_REQUESTED),
        )


@dataclass
class PendingActionEntity:
    id: str
    turn_id: str
    user_id: str
    tool: str
    arguments: dict
    message: str
    status: str
    expires_at: datetime

    @classmethod
    def from_orm(cls, row) -> "PendingActionEntity":
        return cls(
            id=row.ID,
            turn_id=row.TURN_ID,
            user_id=row.USER_ID,
            tool=row.TOOL,
            arguments=row.ARGUMENTS or {},
            message=row.MESSAGE or "",
            status=row.STATUS,
            expires_at=row.EXPIRES_AT,
        )
