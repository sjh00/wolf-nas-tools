"""转移「跳过」与「失败」必须区分。

跳过的典型来源：目标正被其他实例转移（分布式锁未获取）。它是瞬态状态，下一轮会重试，
因此调用方不得：记 ERROR、写转移历史/黑名单、给下载器任务打「已整理」标签（打了会永不重试）。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.entities.transfer_task import SourceType, TransferTask
from app.services.filetransfer_service import (
    TRANSFER_SKIP_PREFIX,
    is_soft_transfer_failure,
    is_transfer_skip,
    skip_message,
    strip_skip_prefix,
)
from app.services.transfer_pipeline import TransferPipeline


class TestSkipMarker:
    def test_skip_message_is_recognized(self):
        assert is_transfer_skip(skip_message("文件正在转移中：/a")) is True

    def test_plain_failure_not_recognized(self):
        assert is_transfer_skip("搜索媒体信息出错") is False
        assert is_soft_transfer_failure("搜索媒体信息出错") is False
        assert is_soft_transfer_failure("无法识别媒体信息") is True
        assert is_soft_transfer_failure("识别失败，无法从文件名中识别出集数") is True
        assert is_soft_transfer_failure("") is True

    def test_empty_not_recognized(self):
        assert is_transfer_skip(None) is False
        assert is_transfer_skip("") is False

    def test_strip_and_idempotent(self):
        assert strip_skip_prefix(skip_message("x")) == "x"
        assert skip_message(skip_message("y")) == f"{TRANSFER_SKIP_PREFIX}y"
        assert strip_skip_prefix("plain") == "plain"


def _make_pipeline() -> tuple[TransferPipeline, MagicMock]:
    blacklist = MagicMock()
    pipeline = TransferPipeline(
        filetransfer=MagicMock(),
        scrape_queue_service=MagicMock(),
        blacklist_repo=blacklist,
        backend_repo=MagicMock(),
    )
    return pipeline, blacklist


def _task(paths: list[str]) -> TransferTask:
    return TransferTask(source_type=SourceType.DIRECTORY, source_id="1", file_paths=paths, operation="link")


class TestPipelineSkipPropagation:
    def test_all_skipped_reported_as_skip(self):
        """全部文件跳过 → 整体结果带跳过标记，调用方据此不记失败"""
        pipeline, _ = _make_pipeline()
        with patch.object(
            pipeline,
            "_process_single",
            side_effect=[
                (False, skip_message("文件正在转移中：/a")),
                (False, skip_message("文件正在转移中：/b")),
            ],
        ):
            ok, msg = pipeline.process(_task(["/a", "/b"]))

        assert ok is False
        assert is_transfer_skip(msg) is True

    def test_mixed_skip_and_failure_keeps_failure_semantics(self):
        """既有跳过又有真失败 → 按失败处理，跳过标记不得掩盖真失败"""
        pipeline, _ = _make_pipeline()
        with patch.object(
            pipeline,
            "_process_single",
            side_effect=[(False, skip_message("文件正在转移中：/a")), (False, "搜索媒体信息出错")],
        ):
            ok, msg = pipeline.process(_task(["/a", "/b"]))

        assert ok is False
        assert is_transfer_skip(msg) is False
        assert "搜索媒体信息出错" in msg

    def test_single_skip_not_recorded_as_success(self):
        """跳过不能被当成成功（否则会被写黑名单而永不重试）"""
        pipeline, blacklist = _make_pipeline()
        with patch.object(pipeline, "_process_single", return_value=(False, skip_message("文件正在转移中：/a"))):
            ok, _msg = pipeline.process(_task(["/a"]))

        assert ok is False
        blacklist.insert.assert_not_called()


class TestDownloaderPostProcessDoesNotTagOnSkip:
    """下载器侧：跳过时不得打「已整理」标签，否则该任务永不重试"""

    def _invoke_post_process(self, success: bool, msg: str) -> MagicMock:
        from app.services import downloader_core as dc

        client = MagicMock()
        captured: dict[str, object] = {}

        def fake_process(task: TransferTask):
            captured["post_process"] = task.post_process
            return (success, msg)

        core = dc.DownloaderCore.__new__(dc.DownloaderCore)
        core._client_factory = MagicMock()
        core._client_factory.monitor_downloader_ids = ["2"]
        core._client_factory.get_downloader_conf.return_value = {
            "name": "qBittorrent",
            "only_wolf_nas": False,
            "match_path": False,
            "rmt_mode": "link",
        }
        core._client_factory.get_client.return_value = client
        client.get_transfer_task.return_value = [{"id": "h1", "path": "/dl/a.mkv", "tags": ["WOLFNAS"]}]
        core._pipeline = MagicMock()
        core._pipeline.process.side_effect = fake_process

        lock_cm = MagicMock()
        lock_cm.__enter__ = MagicMock(return_value=lock_cm)
        lock_cm.__exit__ = MagicMock(return_value=False)
        with patch.object(dc, "_get_downloader_lock", return_value=lock_cm):
            core.transfer("2")

        post_process = captured["post_process"]
        assert callable(post_process)
        post_process(MagicMock(), success, msg)
        return client

    def test_skip_does_not_tag_torrent(self):
        client = self._invoke_post_process(False, skip_message("文件正在转移中：/dl/a.mkv"))
        client.set_torrents_status.assert_not_called()

    def test_real_failure_tags_torrent(self):
        client = self._invoke_post_process(False, "搜索媒体信息出错")
        client.set_torrents_status.assert_called_once()
