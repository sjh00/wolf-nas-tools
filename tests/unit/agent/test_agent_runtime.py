"""Agent Turn 运行时与取消确认测试。"""

import uuid

import pytest

from app.agent.pydantic_agent import PydanticChatAgent
from app.agent.runtime import AgentBusyError, AgentCancelledError, AgentConfirmError, AgentRuntime
from app.db.models import Base
from app.db.session import Database

Base.metadata.create_all(Database().engine)


def test_session_turns_are_serial_and_cancelable():
    runtime = AgentRuntime()
    session_id = f"test-{uuid.uuid4().hex}"
    turn_id = runtime.start_turn(session_id, "1")
    with pytest.raises(AgentBusyError):
        runtime.start_turn(session_id, "1")

    runtime.cancel_turn(turn_id, "1")
    assert runtime.should_cancel(turn_id)
    runtime.finish_turn(turn_id, "cancelled", session_id)
    assert runtime.start_turn(session_id, "1")


def test_pending_action_confirm_reject_and_owner():
    runtime = AgentRuntime()
    session_id = f"test-{uuid.uuid4().hex}"
    turn_id = runtime.start_turn(session_id, "1")
    action = runtime.create_pending(turn_id, "subscribe_delete", {"sub_id": 1}, "确认删除", "1", session_id)

    with pytest.raises(AgentConfirmError):
        runtime.get_pending(action.id, "2")
    assert runtime.get_pending(action.id, "1").arguments == {"sub_id": 1}
    runtime.complete_pending(action.id, turn_id, "rejected", session_id)
    with pytest.raises(AgentConfirmError):
        runtime.get_pending(action.id, "1")


def test_cancel_stops_agent_before_model_call():
    agent = PydanticChatAgent(svc=type("Svc", (), {"ready": True})(), tool_executor=object())
    with pytest.raises(AgentCancelledError):
        agent.chat_with_tools("test", should_cancel=lambda: True)
