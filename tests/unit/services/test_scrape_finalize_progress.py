"""已入库不得阻断订阅进度事件。

真实问题：媒体此前已被标记为「已入库」（例如媒体服务器同步或库对账扫描），
刮削完成时 `already_in_library` 为真 —— 早前实现整体跳过定稿，于是：
文件已在库、转移历史也写了，但订阅的缺失集与进度永不推进，前端一直显示旧集数。

结论：「已入库」只应抑制重复入库通知，不应抑制进度事件。
"""

from unittest.mock import MagicMock

from app.domain.mediatypes import MediaType
from app.media.models import MediaInfo
from app.services.scrape_queue_service import ScrapeQueueService


def _service(already_in_library: bool):
    svc = ScrapeQueueService.__new__(ScrapeQueueService)
    svc._lifecycle = MagicMock()
    svc._lifecycle.is_in_library.return_value = already_in_library
    svc._event_bus = MagicMock()
    svc._receipt_repo = MagicMock()
    svc._receipt_repo.claim.return_value = True
    svc._message = MagicMock()
    svc._record_media = MagicMock()
    svc._scrape_file = MagicMock(return_value=True)
    svc._resolve_backend = MagicMock(return_value=None)
    return svc


def _media() -> MediaInfo:
    media = MediaInfo()
    media.type = MediaType.TV
    media.title = "示例剧集"
    media.tmdb_id = 1
    media.begin_season = 1
    media.begin_episode = 5
    media.end_episode = 5
    media.total_episodes = 10
    return media


def _payload(media: MediaInfo) -> dict:
    from app.utils.json_utils import JsonUtils

    return {
        "media": JsonUtils.model_to_jsonable(media),
        "dir_path": "/media/tv/Show/Season 1",
        "file_name": "Show - S01E05",
        "file_ext": ".mkv",
        "backend_id": "",
        "finalize": {
            "in_path": "/dl/Show.S01E05.mkv",
            "file_item": "/dl/Show.S01E05.mkv",
            "out_path": "/media/tv/Show/Season 1/Show - S01E05.mkv",
            "dist_path": "/media/tv/Show/Season 1",
            "ret_file_path": "/media/tv/Show/Season 1/Show - S01E05.mkv",
            "file_ext": ".mkv",
            "in_from": "Sync",
        },
    }


def _published_types(svc) -> list[str]:
    out = []
    for call in svc._event_bus.publish.call_args_list:
        event = call.args[0]
        out.append(getattr(event, "event_type", ""))
    return out


class TestFinalizeOnAlreadyInLibrary:
    def test_episode_event_published_when_already_in_library(self):
        svc = _service(already_in_library=True)
        media = _media()

        svc._run_file_payload(_payload(media), None)

        types = _published_types(svc)
        assert "media.episode_transferred" in types, "订阅进度事件必须照常发布"

    def test_transfer_finished_event_published_when_already_in_library(self):
        svc = _service(already_in_library=True)
        types_before = None
        svc._run_file_payload(_payload(_media()), None)
        types = _published_types(svc)
        assert "media.transfer_finished" in types
        assert types_before is None

    def test_no_duplicate_notification_when_already_in_library(self):
        svc = _service(already_in_library=True)
        svc._run_file_payload(_payload(_media()), None)
        svc._message.send_transfer_tv_message.assert_not_called()

    def test_notification_sent_when_newly_in_library(self):
        svc = _service(already_in_library=False)
        svc._run_file_payload(_payload(_media()), None)
        svc._message.send_transfer_tv_message.assert_called_once()

    def test_subtitle_not_republished_when_already_in_library(self):
        svc = _service(already_in_library=True)
        svc._run_file_payload(_payload(_media()), None)
        assert "subtitle.download" not in _published_types(svc)

    def test_receipt_still_dedups_repeat_runs(self):
        svc = _service(already_in_library=True)
        getattr(svc._receipt_repo, "claim").return_value = False
        svc._run_file_payload(_payload(_media()), None)
        assert _published_types(svc) == []
