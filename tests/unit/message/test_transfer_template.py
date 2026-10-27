from unittest.mock import MagicMock

from app.message.core.message_builder import MessageBuilder
from app.message.core.template_engine import TemplateEngine
from app.message.template_registry import message_template_registry


def test_web_transfer_message_uses_profile_template():
    message_template_registry.register_pack(
        "test-transfer-template",
        {
            "testprofile": {
                "transfer_finished": {
                    "title": "T {{ profile_label }}",
                    "text": "S {{ source_provider }} K {{ keyword }}",
                }
            }
        },
        labels={"testprofile": "TEST"},
    )
    try:
        builder = MessageBuilder(
            client_manager=MagicMock(),
            dispatcher=MagicMock(),
            messagecenter=MagicMock(),
            template_engine=TemplateEngine(),
        )
        variables = {
            "content_profile": "testprofile",
            "profile_label": "TEST",
            "source_provider": "demo",
            "keyword": "ABC-123",
        }

        title, text = builder._render_system_message("transfer_finished", variables, "fallback-title", "fallback-text")

        assert title == "T TEST"
        assert text == "S demo K ABC-123"
    finally:
        message_template_registry.unregister_plugin("test-transfer-template")
