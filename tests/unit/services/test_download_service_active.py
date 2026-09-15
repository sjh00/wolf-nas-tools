"""正在下载列表的两条硬约束：

1. 只展示**平台推送过**的任务（DOWNLOAD_HISTORY），不列下载器里的其他种子
2. 推送过的任务**绝不隐藏**：hash 对不上时按种子名兜底，仍对不上也要展示
   （否则「下载器里在下载、列表却为空」）
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.download_service import DownloadService

_PUSHED_HASH = "hash1"
_PUSHED_NAME = "Some.Release.2024.mkv"


def _make_service(client_progress, client_progress_raises=False, downloader_enabled=1):
    """构造 DownloadService。

    :param client_progress: 下载器返回的「正在下载」全量列表（None 表示查询失败）
    """
    task = SimpleNamespace(
        downloader="2",
        download_id=_PUSHED_HASH,
        state="downloading",
        torrent=_PUSHED_NAME,
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

    conf = {"id": "2", "name": "qBittorrent", "type": "qbittorrent", "enabled": downloader_enabled}
    downloader = MagicMock()
    # 真实语义：无参 → {下载器ID: 配置} 映射；传 id → 单个配置
    downloader.get_downloader_conf.side_effect = lambda did=None: conf if did else {"2": conf}
    # 真实语义：未启用的下载器 get_client 返回 None
    downloader.get_downloader.return_value = client if downloader_enabled else None

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


def _pushed(progress: float = 42.5, task_id: str = _PUSHED_HASH, name: str = _PUSHED_NAME) -> dict:
    return {"id": task_id, "name": name, "progress": progress, "state": "Downloading", "speed": "1MB/s"}


class TestQueryFailure:
    def test_query_failure_does_not_mark_completed(self):
        """下载器查询失败（None）时保持原状态，绝不能把任务标成 completed"""
        svc, history_repo, _client = _make_service(None)

        result = svc.get_downloading_with_media_info()

        assert result["items"] == []
        history_repo.batch_update_state.assert_not_called()

    def test_exception_is_treated_as_failure_not_missing(self):
        """查询抛异常同样按失败处理，不得标记完成"""
        svc, history_repo, _client = _make_service(None, client_progress_raises=True)

        result = svc.get_downloading_with_media_info()

        assert result["items"] == []
        history_repo.batch_update_state.assert_not_called()


class TestOnlyPushedTasksShown:
    """约束 1：只展示平台推送过的任务"""

    def test_downloader_only_torrent_not_listed(self):
        """用户在下载器里手动添加的种子（本地无记录）不得出现在列表里"""
        progress = [
            _pushed(),
            {"id": "manual-hash", "name": "User.Manual.Download.mkv", "progress": 55.0, "state": "Downloading"},
        ]
        svc, _history_repo, _client = _make_service(progress)

        result = svc.get_downloading_with_media_info()

        ids = [i["id"] for i in result["items"]]
        assert ids == [_PUSHED_HASH]
        assert "manual-hash" not in ids

    def test_local_record_enriches_title(self):
        """展示的是推送过的任务，并用本地记录的标题/海报富化"""
        svc, _history_repo, _client = _make_service([_pushed()])

        result = svc.get_downloading_with_media_info()

        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["id"] == _PUSHED_HASH
        assert item["title"] == "测试影片 (2024) "
        assert item["progress"] == 42.5
        assert item["downloader_name"] == "qBittorrent"
        assert item["save_path"] == "/downloads"


class TestPushedTaskNeverHidden:
    """约束 2：推送过的任务绝不隐藏"""

    def test_hash_mismatch_falls_back_to_name(self):
        """hash 对不上时按种子名兜底匹配 → 拿到真实进度"""
        progress = [_pushed(progress=7.5, task_id="different-hash")]
        svc, _history_repo, _client = _make_service(progress)

        result = svc.get_downloading_with_media_info()

        assert len(result["items"]) == 1
        assert result["items"][0]["progress"] == 7.5

    def test_unmatched_pushed_task_still_listed(self):
        """hash 与种子名都对不上 → 仍然展示（无实时进度），而不是消失"""
        progress = [{"id": "other", "name": "Other.mkv", "progress": 10.0, "state": "Downloading"}]
        svc, history_repo, _client = _make_service(progress)

        result = svc.get_downloading_with_media_info()

        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["id"] == _PUSHED_HASH
        assert item["title"] == "测试影片 (2024) "
        # 不得因比对不到就改状态或标完成
        history_repo.batch_update_state.assert_not_called()

    def test_unmatched_logs_once_across_polls(self):
        """比对不到要留痕，且按任务去重避免 30s 轮询刷屏"""
        progress = [{"id": "other", "name": "Other.mkv", "progress": 10.0, "state": "Downloading"}]
        svc, _history_repo, _client = _make_service(progress)

        with patch("app.services.download_service.log") as mock_log:
            svc.get_downloading_with_media_info()
            svc.get_downloading_with_media_info()
            svc.get_downloading_with_media_info()

        assert mock_log.warn.call_count == 1


class TestStatusReconciliation:
    def test_completed_task_exits_list(self):
        """进度达 100% → 退出「正在下载」列表并标记完成"""
        svc, history_repo, _client = _make_service([_pushed(progress=100.0)])

        result = svc.get_downloading_with_media_info()

        assert result["items"] == []
        (updated,), _ = history_repo.batch_update_state.call_args
        assert updated == [("2", _PUSHED_HASH, "completed")]

    def test_disabled_downloader_skipped(self):
        """未启用的下载器不参与查询"""
        svc, _history_repo, client = _make_service([], downloader_enabled=0)

        result = svc.get_downloading_with_media_info()

        assert result["items"] == []
        client.get_downloading_progress.assert_not_called()

    def test_no_history_returns_empty(self):
        """本地无任何推送记录 → 即使下载器有一堆任务也不展示"""
        svc, history_repo, client = _make_service([_pushed()])
        history_repo.get_active_downloads.return_value = []

        result = svc.get_downloading_with_media_info()

        assert result == {"items": [], "total": 0}
        client.get_downloading_progress.assert_not_called()


class TestPagination:
    def test_page_slice(self):
        """分页只作用于平台推送的任务集合"""
        svc, history_repo, _client = _make_service([_pushed(), _pushed(task_id="hash2", name="Second.mkv")])
        second = SimpleNamespace(
            downloader="2",
            download_id="hash2",
            state="downloading",
            torrent="Second.mkv",
            save_path="",
            year="",
            season_episode="",
            title="第二部",
            poster="",
        )
        first = history_repo.get_active_downloads.return_value[0]
        history_repo.get_active_downloads.return_value = [first, second]

        result = svc.get_downloading_with_media_info(page=1, page_size=1)

        assert result["total"] == 2
        assert len(result["items"]) == 1
