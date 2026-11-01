"""Provider 网关：统一超时、取消与同步 Provider 适配。"""

import asyncio
from collections.abc import Callable

from app.agent.runtime import AgentCancelledError


class ProviderTimeoutError(TimeoutError):
    pass


class ProviderGateway:
    def __init__(self, service, timeout: float = 120.0):
        self._service = service
        self._timeout = timeout

    async def request(
        self,
        messages: list[dict],
        tools: list[dict],
        on_token: Callable[[str], None] | None,
        on_reasoning: Callable[[str], None] | None,
        on_tool_call: Callable[[str, dict, str], None] | None,
        should_cancel: Callable[[], bool] | None = None,
    ):
        if should_cancel and should_cancel():
            raise AgentCancelledError("用户取消了请求")
        try:
            result = await asyncio.wait_for(
                self._service.chat_tool_calls_async(
                    messages=messages,
                    tools=tools,
                    on_token=on_token,
                    on_reasoning=on_reasoning,
                ),
                timeout=self._timeout,
            )
        except TimeoutError as err:
            raise ProviderTimeoutError(f"模型请求超过 {self._timeout:g}s 未响应") from err
        if should_cancel and should_cancel():
            raise AgentCancelledError("用户取消了请求")
        return result
