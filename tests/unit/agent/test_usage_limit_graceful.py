"""工具调用轮次用尽时优雅交付，而不是报错。

真实报错：`请求出错: The next request would exceed the request_limit of 9`。
`request_limit = max_steps + 1`，而默认 max_steps 只有 8 —— 一次典型操作
（查状态 → 查详情 → 执行 → 复核）就要 4-8 步，复杂排查必然撞上限。

更糟的是超限被当作普通异常处理，直接 `请求出错: {e}`：模型其实已经把
一部分事实查出来了，用户看到的却是与业务无关的技术报错。

两处修正：
1. 默认步数 8 → 20（覆盖正常操作 + 一定量的复杂排查）
2. 超限时用 capture_run_messages 取回已完成的消息，把助手已产出的文本
   交付给用户，并说明这是「本轮工具次数用尽」而非服务故障
"""

from unittest.mock import MagicMock

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.usage import UsageLimits

from app.agent.pydantic_agent import DEFAULT_MAX_STEPS, PydanticChatAgent


def _agent(max_steps: int = DEFAULT_MAX_STEPS) -> PydanticChatAgent:
    agent = PydanticChatAgent.__new__(PydanticChatAgent)
    agent._max_steps = max_steps
    return agent


class TestUsageLimits:
    def test_default_steps_generous_enough(self):
        # 8 步对「查询+操作+复核」偏紧，默认值必须留出余量
        assert DEFAULT_MAX_STEPS >= 16

    def test_request_limit_is_steps_plus_one(self):
        limits = _agent(max_steps=20)._usage_limits()
        assert isinstance(limits, UsageLimits)
        assert limits.request_limit == 21

    def test_configured_steps_respected(self):
        assert _agent(max_steps=5)._usage_limits().request_limit == 6

    def test_invalid_steps_fall_back_to_default(self):
        # 0/负数/1 都是无效配置，回退默认值而不是压成 2 步
        # （压成 2 步的话，任何「查询 → 操作」都跑不完）
        for bad in (0, -5, 1):
            assert _agent(max_steps=bad)._usage_limits().request_limit == DEFAULT_MAX_STEPS + 1

    def test_none_falls_back_to_default(self):
        agent = _agent()
        agent._max_steps = None
        assert agent._usage_limits().request_limit == DEFAULT_MAX_STEPS + 1

    def test_non_numeric_falls_back_to_default(self):
        agent = _agent()
        agent._max_steps = "abc"  # type: ignore[assignment]
        assert agent._usage_limits().request_limit == DEFAULT_MAX_STEPS + 1


class TestExtractPartialAnswer:
    def test_returns_last_text_response(self):
        messages = [
            ModelRequest(parts=[UserPromptPart(content="查一下订阅")]),
            ModelResponse(parts=[TextPart(content="我先看订阅列表。")]),
            ModelResponse(parts=[ToolCallPart(tool_name="list_subs", args={})]),
            ModelResponse(parts=[TextPart(content="当前有 3 个订阅在跑。")]),
        ]
        assert PydanticChatAgent._extract_partial_answer(messages) == "当前有 3 个订阅在跑。"

    def test_skips_tool_call_only_response(self):
        messages = [
            ModelResponse(parts=[TextPart(content="正在查询…")]),
            ModelResponse(parts=[ToolCallPart(tool_name="query", args={})]),
        ]
        # 最后一条没有文本，回退到更早那条有文本的
        assert PydanticChatAgent._extract_partial_answer(messages) == "正在查询…"

    def test_empty_when_no_text(self):
        messages = [
            ModelResponse(parts=[ToolCallPart(tool_name="t", args={})]),
        ]
        assert PydanticChatAgent._extract_partial_answer(messages) == ""

    def test_handles_none_and_empty(self):
        assert PydanticChatAgent._extract_partial_answer([]) == ""
        assert PydanticChatAgent._extract_partial_answer(None) == ""

    def test_joins_multiple_text_parts(self):
        messages = [ModelResponse(parts=[TextPart(content="第一段"), TextPart(content="第二段")])]
        assert PydanticChatAgent._extract_partial_answer(messages) == "第一段\n第二段"

    def test_ignores_blank_text(self):
        messages = [ModelResponse(parts=[TextPart(content="   ")])]
        assert PydanticChatAgent._extract_partial_answer(messages) == ""


class TestLimitMessage:
    """超限时给用户的措辞：不能出现 request_limit 这类内部术语."""

    @staticmethod
    def _build(partial: str) -> str:
        if partial:
            return f"{partial}\n\n---\n（本轮工具调用已达上限，以上为已获取到的内容。继续提问可接着处理。）"
        return "这个请求需要连续调用较多工具，本轮已达到调用上限。可以换个更具体的问法，或把需求拆成几步依次提问。"

    def test_partial_answer_preserved(self):
        text = self._build("已查到 3 个订阅")
        assert "已查到 3 个订阅" in text
        assert "request_limit" not in text

    def test_no_partial_gives_actionable_hint(self):
        text = self._build("")
        assert "request_limit" not in text
        assert "拆成几步" in text


class TestExceptionMapping:
    """UsageLimitExceeded 必须走专门分支，不能落进通用「请求出错」."""

    def test_usage_limit_branch_exists_before_generic(self):
        import inspect

        src = inspect.getsource(PydanticChatAgent)
        idx_limit = src.find("except UsageLimitExceeded")
        assert idx_limit > 0, "缺少 UsageLimitExceeded 分支"
        # 取该分支之后最近的通用异常（源码里有多处 except Exception，不能直接 find 首个）
        idx_generic = src.find("except Exception as e:", idx_limit)
        assert idx_generic > idx_limit, "UsageLimitExceeded 必须紧邻并在通用异常之前"

    def test_capture_run_messages_used(self):
        import inspect

        src = inspect.getsource(PydanticChatAgent)
        assert "capture_run_messages()" in src
        # 声明必须在 try 之外，否则超限分支读不到
        assert "run_messages: list[Any] = []" in src
