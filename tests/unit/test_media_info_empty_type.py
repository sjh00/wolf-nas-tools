"""识别失败时的媒体信息必须能安全流转。

真实故障：LLM 限流降级后识别结果为「未识别」，下载事件里 ``type`` 是空串，
``MediaInfo`` 校验直接抛 ``Input should be 'tv', 'movie', 'anime' or 'unknown'``，
通知模板又对 ``type.display_name`` 取值（None），两处合起来让「创建下载任务」整条失败。
"""

from unittest.mock import MagicMock

import pytest

from app.domain.media_types import ProviderMediaType
from app.media.models import MediaInfo
from app.message.core.message_builder import MessageBuilder, _message_variables, _type_label


class TestEmptyTypeTolerated:
    @pytest.mark.parametrize("raw", ["", "   ", None])
    def test_blank_type_becomes_none(self, raw):
        assert MediaInfo.model_validate({"title": "x", "type": raw}).type is None

    def test_missing_type_is_none(self):
        assert MediaInfo.model_validate({"title": "x"}).type is None

    def test_valid_type_still_parsed(self):
        assert MediaInfo.model_validate({"title": "x", "type": "movie"}).type is ProviderMediaType.MOVIE
        assert MediaInfo.model_validate({"title": "x", "type": "TV"}).type is ProviderMediaType.SERIES

    def test_chinese_alias_parsed(self):
        assert MediaInfo.model_validate({"title": "x", "type": "电视剧"}).type is ProviderMediaType.SERIES
        assert MediaInfo.model_validate({"title": "x", "type": "电影"}).type is ProviderMediaType.MOVIE

    def test_unknown_value_degrades_to_unknown(self):
        assert MediaInfo.model_validate({"title": "x", "type": "???garbage"}).type is ProviderMediaType.UNKNOWN

    def test_roundtrip_through_event_payload(self):
        """model_dump 会输出空串 type，回灌校验必须仍然成功（事件总线路径）。"""
        empty = MediaInfo()
        restored = MediaInfo.model_validate(empty.to_dict())
        assert restored.type is None

class TestTypeLabelWithoutType:
    def test_label_falls_back_to_unknown(self):
        media = MediaInfo()
        assert _type_label(media, "default") == "未知"
        assert _message_variables(media)["type_label"] == "未知"

    def test_label_keeps_real_type(self):
        media = MediaInfo.model_validate({"type": "tv"})
        assert _type_label(media, "default") == "电视剧"

    def test_profile_label_still_wins(self):
        media = MediaInfo()
        assert _type_label(media, "profiles:anime") != ""

class TestDownloadMessageWithEmptyMedia:
    def test_send_download_message_does_not_raise(self):
        """未识别媒体也要能发出下载通知，而不是把任务创建拖崩。"""
        media = MediaInfo()
        media.org_string = "Some.Torrent.Name"
        builder = MessageBuilder(MagicMock(), MagicMock(), MagicMock(), None)
        builder.send_download_message("qb", media, "默认", "qBittorrent")

    def test_download_started_event_handler_accepts_empty_type(self):
        from app.events.constants import DOWNLOAD_STARTED
        from app.events.payloads import DownloadStartedPayload
        from app.infrastructure.event import Event
        from app.services.download.handlers import handle_download_started

        event = Event(
            event_type=DOWNLOAD_STARTED,
            payload=DownloadStartedPayload(
                media_info=MediaInfo().to_dict(),
                is_paused=False,
                tag=None,
                download_dir="",
                download_setting=None,
                torrent_file="",
                downloader_id="qb1",
                download_id="h1",
            ),
        )
        # 只要不抛异常即可：生命周期落库失败已被内部兜底
        handle_download_started(event)
