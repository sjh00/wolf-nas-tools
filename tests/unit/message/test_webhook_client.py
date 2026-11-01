"""Webhook 消息客户端配置解析回归测试。"""

import pytest

from app.plugin_framework.builtin_plugins.msg_webhook.backend.message_client import Webhook


class TestWebhookReadConfig:
    def test_missing_query_params_does_not_crash(self):
        # 可选字段留空（None）时不应在 strip() 处崩溃
        client = Webhook({"url": "https://example.com/hook", "method": "POST"})
        assert client._query_params is None

    def test_blank_query_params_returns_none(self):
        client = Webhook({"url": "https://example.com/hook", "method": "POST", "query_params": "   "})
        assert client._query_params is None

    def test_valid_query_params_parsed(self):
        client = Webhook({"url": "https://example.com/hook", "method": "POST", "query_params": '{"search": "kw"}'})
        assert client._query_params == {"search": "kw"}

    def test_invalid_query_params_raises(self):
        with pytest.raises(ValueError):
            Webhook({"url": "https://example.com/hook", "method": "POST", "query_params": "{bad"})
