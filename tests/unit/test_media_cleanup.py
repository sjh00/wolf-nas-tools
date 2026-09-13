"""MediaCleanupService 单元测试 — 按文件锚点清理硬链接链."""

import os
from unittest.mock import MagicMock

import pytest

from app.services.media_cleanup_service import MediaCleanupService


class _FakeTransferLog:
    def __init__(self, sid, src_path, src_fn, dst_path, dst_fn):
        self.ID = sid
        self.SOURCE_PATH = src_path
        self.SOURCE_FILENAME = src_fn
        self.DEST_PATH = dst_path
        self.DEST_FILENAME = dst_fn


class _FakeDownloadRec:
    def __init__(self, rid, downloader, download_id, save_path):
        self.ID = rid
        self.DOWNLOADER = downloader
        self.DOWNLOAD_ID = download_id
        self.SAVE_PATH = save_path


@pytest.fixture
def cleanup_svc():
    cleanup = MagicMock()
    history = MagicMock()
    downloader_core = MagicMock()
    download_repo = MagicMock()
    event_bus = MagicMock()
    svc = MediaCleanupService(
        cleanup_service=cleanup,
        history_manager=history,
        downloader_core=downloader_core,
        download_repo=download_repo,
        event_bus=event_bus,
    )
    return svc


class TestFindChainPaths:
    def test_includes_anchor_and_hardlink_brothers(self, monkeypatch, tmp_path):
        svc = MediaCleanupService.__new__(MediaCleanupService)
        anchor_path = tmp_path / "Show.mkv"
        anchor_path.write_text("x")
        anchor = str(anchor_path)

        def fake_find_hardlinks(self, file=None, fdir=None):
            return [
                {
                    "file": str(tmp_path / "seed" / "Show.mkv"),
                    "filename": "Show.mkv",
                    "filepath": str(tmp_path / "seed"),
                },
                {
                    "file": str(tmp_path / "movie" / "Show" / "Show.mkv"),
                    "filename": "Show.mkv",
                    "filepath": str(tmp_path / "movie" / "Show"),
                },
            ]

        from app.utils.system_utils import SystemUtils

        monkeypatch.setattr(SystemUtils, "find_hardlinks", fake_find_hardlinks)
        result = svc._find_chain_paths(anchor)
        assert os.path.normpath(anchor) in result
        assert os.path.normpath(str(tmp_path / "seed" / "Show.mkv")) in result
        assert os.path.normpath(str(tmp_path / "movie" / "Show" / "Show.mkv")) in result


class TestCleanupFileChain:
    def test_deletes_transfer_and_downloader(self, cleanup_svc, tmp_path):
        svc = cleanup_svc
        anchor_path = tmp_path / "Show.mkv"
        anchor_path.write_text("x")
        anchor = str(anchor_path)
        svc._find_chain_paths = MagicMock(return_value=[os.path.normpath(anchor)])
        svc._history.get_transfer_logs_by_paths.return_value = [
            _FakeTransferLog(1, str(tmp_path / "seed"), "Show.mkv", str(tmp_path / "movie" / "Show"), "Show.mkv")
        ]
        svc._download_repo.get_download_history_list_by_path.return_value = [
            _FakeDownloadRec(10, "qb", "hash1", str(tmp_path / "seed"))
        ]

        result = svc.cleanup_file_chain(anchor)

        assert result["deleted_transfer_logs"] == 1
        svc._cleanup.delete_history.assert_called_once()
        assert svc._cleanup.delete_history.call_args.kwargs.get("flag") == "del_all"
        svc._downloader_core.delete_torrents.assert_called_once()
        _, kwargs = svc._downloader_core.delete_torrents.call_args
        assert kwargs.get("delete_file") is True
        svc._download_repo.delete_by_ids.assert_called_once()
        assert svc._download_repo.delete_by_ids.call_args[0][0] == [10]

    def test_keeps_other_version_if_not_hardlinked(self, cleanup_svc, tmp_path):
        """同作品但非硬链接的其它版本文件不应被清理（假链接链只含锚点）。"""
        svc = cleanup_svc
        anchor_path = tmp_path / "Show.mkv"
        anchor_path.write_text("x")
        anchor = str(anchor_path)
        svc._find_chain_paths = MagicMock(return_value=[os.path.normpath(anchor)])
        svc._history.get_transfer_logs_by_paths.return_value = [
            _FakeTransferLog(2, str(tmp_path / "seed"), "Show.mkv", str(tmp_path / "movie" / "Show"), "Show.mkv")
        ]
        svc._download_repo.get_download_history_list_by_path.return_value = []

        result = svc.cleanup_file_chain(anchor)
        assert result["deleted_transfer_logs"] == 1


class TestSourcePolicyKeep:
    def test_keep_only_deletes_dest_keeps_source_and_records(self, cleanup_svc, tmp_path):
        """source_policy='keep'：只删媒体库目标，不删源文件/记录/下载器任务。"""
        svc = cleanup_svc
        anchor_path = tmp_path / "Show.mkv"
        anchor_path.write_text("x")
        anchor = str(anchor_path)
        dest_path = tmp_path / "movie" / "Show"
        dest_path.mkdir(parents=True)
        dest_file = dest_path / "Show.mkv"
        dest_file.write_text("x")
        svc._find_chain_paths = MagicMock(return_value=[os.path.normpath(anchor)])
        svc._history.get_transfer_logs_by_paths.return_value = [
            _FakeTransferLog(3, str(tmp_path / "seed"), "Show.mkv", str(dest_path), "Show.mkv")
        ]

        result = svc.cleanup_file_chain(anchor, source_policy="keep")

        # 只删媒体库目标，不删转移记录，不删下载器任务
        assert result["deleted_transfer_logs"] == 0
        assert result["deleted_torrents"] == []
        assert result["source_policy"] == "keep"
        svc._cleanup.delete_history.assert_not_called()
        svc._downloader_core.delete_torrents.assert_not_called()
        # 调用了 delete_media_file 删目标
        assert svc._cleanup.delete_media_file.called
        # 发布媒体库删除事件
        assert svc._event_bus.publish.called
