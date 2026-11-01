"""Webhook 相关插件显示名区分的回归测试。

插件市场同时存在事件级 `webhook` 与消息渠道 `msg_webhook`，
两者显示名必须不同，避免用户误以为重复/冲突。
"""

import json
from pathlib import Path

BASE = Path("src/app/plugin_framework/builtin_plugins")


def _manifest(plugin_id: str) -> dict:
    return json.loads((BASE / plugin_id / "manifest.json").read_text(encoding="utf-8"))


def test_webhook_and_msg_webhook_have_distinct_names():
    event = _manifest("webhook")
    channel = _manifest("msg_webhook")
    assert event["id"] == "webhook"
    assert channel["id"] == "msg_webhook"
    assert event["name"]
    assert channel["name"]
    assert event["name"] != channel["name"]
