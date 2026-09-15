"""正在下载列表：查询失败不得误标已完成。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.download_service import DownloadService


def _make_service(client_progress):
    """构造 DownloadService，下载器进度查询返回 client_progress"""
    task = SimpleNamespace(
        downloader="2",
        download_id="hash1",
        state="downloading",
        torrent="Some.Release.2024.mkv",
        save_path="/downloads",
        year="2024",
        season_episode="",
        title="测试影片",
        poster="",
    )

    history_repo = MagicMock()
    history_repo.get_active_downloads.return_value = [task]

    client = MagicMock()
    client.get_downloading_progress.return_value = client_progress

    downloader = MagicMock()
    downloader.get_downloader_conf.return_value = {"name": "qBittorrent", "type": "qbittorrent"}
    downloader.get_downloader.return_value = client

    svc = DownloadService(
        downloader=downloader,
        searcher=MagicMock(),
        media_service=MagicMock(),
        sites=MagicMock(),
        site_engine=MagicMock(),
        indexer_service=MagicMock(),
        torrent_remover=MagicMock(),
        download_history_repo=history_repo,
    )
    return svc, history_repo, client


class TestActiveDownloadQueryFailure:
    def test_query_failure_does_not_mark_completed(self):
        """下载器查询失败（None）时跳过本轮，绝不能把任务标成 completed"""
        svc, history_repo, _client = _make_service(None)

        result = svc.get_downloading_with_media_info()

        assert result["items"] == []
        history_repo.batch_update_state.assert_not_called()

    def test_exception_is_treated_as_failure_not_missing(self):
        """查询抛异常同样按失败处理，不得标记完成"""
        svc, history_repo, client = _make_service(None)
        client.get_downloading_progress.side_effect = RuntimeError("qb 掉线")

        result = svc.get_downloading_with_media_info()

        assert result["items"] == []
        history_repo.batch_update_state.assert_not_called()

    def test_missing_task_marked_completed(self):
        """查询成功但任务确实不在下载器中（[]）→ 可以安全标记完成"""
        svc, history_repo, _client = _make_service([])

        result = svc.get_downloading_with_media_info()

        assert result["items"] == []
        history_repo.batch_update_state.assert_called_once()
        (items,), _ = history_repo.batch_update_state.call_args
        assert items == [("2", "hash1", "completed")]

    def test_still_downloading_is_returned(self):
        """任务仍在下载中 → 出现在列表里"""
        progress = {
            "id": "hash1",
            "name": "Some.Release.2024.mkv",
            "progress": 42.5,
            "state": "Downloading",
            "speed": "1MB/s",
        }
        svc, _history_repo, _client = _make_service([progress])

        result = svc.get_downloading_with_media_info()

        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["id"] == "hash1"
        assert item["progress"] == 42.5
        assert item["downloader_name"] == "qBittorrent"
