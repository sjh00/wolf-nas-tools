"""ProviderGateway 超时与取消测试。"""

import asyncio

import pytest

from app.agent.providers.gateway import ProviderGateway, ProviderTimeoutError
from app.agent.runtime import AgentCancelledError


class _Service:
    def __init__(self, delay: float = 0.0):
        self.delay = delay

    async def chat_tool_calls_async(self, messages, tools, on_token=None, on_reasoning=None):
        await asyncio.sleep(self.delay)
        return type("Resp", (), {"content": "ok", "tool_calls": []})()


def test_gateway_returns_provider_response():
    gateway = ProviderGateway(_Service(), timeout=1)
    result = asyncio.run(gateway.request([], [], lambda _: None, lambda _: None, lambda *_: None))
    assert result.content == "ok"


def test_gateway_times_out():
    gateway = ProviderGateway(_Service(delay=0.05), timeout=0.01)
    with pytest.raises(ProviderTimeoutError):
        asyncio.run(gateway.request([], [], lambda _: None, lambda _: None, lambda *_: None))


def test_gateway_honors_cancellation():
    gateway = ProviderGateway(_Service())
    with pytest.raises(AgentCancelledError):
        asyncio.run(
            gateway.request([], [], lambda _: None, lambda _: None, lambda *_: None, should_cancel=lambda: True)
        )
