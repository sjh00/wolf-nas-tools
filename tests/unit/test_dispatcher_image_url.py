from unittest.mock import MagicMock

from app.message.core.dispatcher import MessageDispatcher


def test_external_image_relative_url_is_made_absolute():
    dispatcher = MessageDispatcher(MagicMock(), MagicMock(), domain="https://example.com")
    dispatcher._queue = MagicMock()
    client = {"name": "wechat", "client": MagicMock()}
    client["client"].send_msg.return_value = (True, "")

    dispatcher._do_sendmsg(client, "title", "text", "/img/blur?url=x", "", "")

    client["client"].send_msg.assert_called_once()
    assert client["client"].send_msg.call_args.kwargs["image"] == "https://example.com/img/blur?url=x"
