"""Synology Chat 机器人可见用户获取：基于 webhook URL 构造并优先使用 URL 内 token。

回归：此前用 get_base_url 只取 scheme://netloc，丢失反向代理路径前缀，
且使用单独的 token 字段、异常被静默吞掉，导致 user_list 得到空用户。
"""

from typing import Any, cast
from unittest.mock import MagicMock

from app.plugin_framework.builtin_plugins.msg_synologychat.backend.message_client import SynologyChat


def _client(webhook_url, token, body):
    client = SynologyChat.__new__(SynologyChat)
    client._webhook_url = webhook_url
    client._token = token
    client._domain = None
    client._req = MagicMock()
    client._req.get.return_value.json.return_value = body
    return client


def test_user_list_url_keeps_path_prefix_and_uses_url_token():
    url = "http://nas:8888/proxy/webapi/entry.cgi?api=SYNO.Chat.External&method=incoming&version=2&token=URITOKEN"
    client = _client(url, "WRONG", {"success": True, "data": {"users": [{"user_id": 7}, {"user_id": 9}]}})

    users = getattr(client, "_SynologyChat__get_bot_users")()

    assert users == [7, 9]
    called_url = cast(Any, client._req).get.call_args.kwargs["url"]
    assert called_url.startswith("http://nas:8888/proxy/webapi/entry.cgi?")
    assert "method=user_list" in called_url
    assert "token=URITOKEN" in called_url


def test_user_list_returns_empty_when_no_visible_users():
    url = "http://nas:8888/webapi/entry.cgi?api=SYNO.Chat.External&method=incoming&version=2&token=T"
    client = _client(url, "T", {"success": True, "data": {"users": []}})

    assert getattr(client, "_SynologyChat__get_bot_users")() == []
