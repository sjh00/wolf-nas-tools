"""正在下载列表：以下载器为准，查询失败不得误标已完成。"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.download_service import DownloadService


def _make_service(client_progress, client_progress_raises=False, downloader_enabled=1):
    """构造 DownloadService。

    :param client_progress: 下载器返回的「正在下载」全量列表（None 表示查询失败）
    :param downloader_enabled: 下载器启用标记，0 表示未启用（应被跳过）
    """
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
    if client_progress_raises:
        client.get_downloading_progress.side_effect = RuntimeError("qb 掉线")
    else:
        client.get_downloading_progress.return_value = client_progress

    downloader = MagicMock()
    # get_downloader_conf() 无参时返回 {下载器ID: 配置} 映射
    downloader.get_downloader_conf.return_value = {
        "2": {"id": "2", "name": "qBittorrent", "type": "qbittorrent", "enabled": downloader_enabled},
    }
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

    def test_missing_task_logs_once_across_polls(self):
        """任务在下载器中查不到时必须留痕（此前完全静默，导致列表为空却无从排查），
        且按任务去重，避免 30s 轮询刷屏"""
        svc, _history_repo, _client = _make_service([])

        with patch("app.services.download_service.log") as mock_log:
            svc.get_downloading_with_media_info()
            first = len(mock_log.warn.call_args_list)
            svc.get_downloading_with_media_info()
            svc.get_downloading_with_media_info()

        assert first == 1, "首次查不到任务应告警一条"
        assert len(mock_log.warn.call_args_list) == 1, "同一任务重复轮询不应重复告警"

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


class TestDownloaderIsSourceOfTruth:
    """以下载器为准（v3 语义）：本地记录缺失或 hash 不一致时，任务仍必须展示。

    旧实现以本地 DOWNLOAD_HISTORY 为准、拿 DOWNLOAD_ID 去下载器逐个查，
    一旦记录缺失或 hash 不一致，任务就整条消失 —— 表现为「下载器里明明在
    下载、列表却恒为空」。以下载器为准后此依赖被移除。
    """

    def test_torrent_without_local_record_still_listed(self):
        """下载器里有、本地无记录（手动添加/记录缺失）→ 仍展示，用下载器名称兜底"""
        progress = [
            {"id": "unknown-hash", "name": "Solo.Torrent.2024.mkv", "progress": 10.0, "state": "Downloading"},
        ]
        svc, history_repo, _client = _make_service(progress)

        result = svc.get_downloading_with_media_info()

        items = result["items"]
        assert len(items) == 1
        assert items[0]["id"] == "unknown-hash"
        assert items[0]["name"] == "Solo.Torrent.2024.mkv"
        assert items[0]["title"] == "Solo.Torrent.2024.mkv"
        # 本地记录 hash1 确实不在下载器中 → 收敛为 completed；
        # 但下载器里真实存在的 unknown-hash 必须已展示（这正是本次修复的核心）
        (updated,), _ = history_repo.batch_update_state.call_args
        assert updated == [("2", "hash1", "completed")]

    def test_local_record_hash_mismatch_does_not_hide_torrent(self):
        """本地记录 hash 与下载器不一致时，真实下载中的任务仍必须出现在列表里"""
        progress = [
            {"id": "real-hash", "name": "Boyhood.2014.mkv", "progress": 3.0, "state": "Downloading"},
        ]
        svc, history_repo, _client = _make_service(progress)

        result = svc.get_downloading_with_media_info()

        assert [i["id"] for i in result["items"]] == ["real-hash"]

    def test_disabled_downloader_skipped(self):
        """未启用的下载器不参与查询"""
        svc, _history_repo, client = _make_service([], downloader_enabled=0)

        result = svc.get_downloading_with_media_info()

        assert result["items"] == []
        client.get_downloading_progress.assert_not_called()

    def test_local_record_enriches_title(self):
        """本地有记录时，用记录中的标题/海报富化展示"""
        progress = [{"id": "hash1", "name": "raw.name.mkv", "progress": 20.0, "state": "Downloading"}]
        svc, _history_repo, _client = _make_service(progress)

        result = svc.get_downloading_with_media_info()

        item = result["items"][0]
        assert item["title"] == "测试影片 (2024) "
        assert item["save_path"] == "/downloads"
