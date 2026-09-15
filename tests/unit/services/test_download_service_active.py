"""「正在下载」列表的语义与性能约束。

语义：只展示**平台推送过**的任务（DOWNLOAD_HISTORY），并区分三种情况
- 下载器查询失败 → 保持原状态（不得误标完成）
- 下载器里查不到该任务 → 按完成处理并留痕
- 下载器里仍在下载 → 展示实时进度

性能：必须**按 hash 批量查询**（ids=...）。曾因改成"取下载器全部任务再本地匹配"
导致超时——客户端为每个种子解析属性/tracker，代价是每种子 3 次额外 HTTP 请求，
全量拉取会把接口拖过前端的 30s 超时。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.download_service import DownloadService

_PUSHED_HASH = "hash1"
_PUSHED_NAME = "Some.Release.2024.mkv"


def _make_service(client_progress, client_progress_raises=False, downloader_enabled=1):
    """构造 DownloadService。

    :param client_progress: 下载器返回的进度列表（None 表示查询失败）
    """
    task = SimpleNamespace(
        downloader="2",
        download_id=_PUSHED_HASH,
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


def _progress(progress: float = 42.5, task_id: str = _PUSHED_HASH, name: str = _PUSHED_NAME) -> dict:
    return {"id": task_id, "name": name, "progress": progress, "state": "Downloading", "speed": "1MB/s"}


class TestMustQueryByIds:
    """性能回归守卫：不得改成不限 ids 的全量拉取。"""

    def test_queries_with_ids(self):
        svc, _repo, client = _make_service([_progress()])

        svc.get_downloading_with_media_info()

        assert client.get_downloading_progress.call_count == 1
        kwargs = client.get_downloading_progress.call_args.kwargs
        assert kwargs.get("ids") == [_PUSHED_HASH], (
            "必须按平台推送的 hash 查询；不限 ids 会全量拉取并逐个解析 tracker，"
            "导致接口超过前端 30s 超时"
        )


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
    """只展示平台推送过的任务"""

    def test_shows_pushed_task_with_progress(self):
        svc, _repo, _client = _make_service([_progress()])

        result = svc.get_downloading_with_media_info()

        assert result["total"] == 1
        item = result["items"][0]
        assert item["id"] == _PUSHED_HASH
        assert item["progress"] == 42.5
        assert item["title"] == "测试影片 (2024) "
        assert item["downloader_name"] == "qBittorrent"
        assert item["save_path"] == "/downloads"

    def test_no_history_returns_empty_without_querying(self):
        """本地无推送记录 → 即使下载器有一堆任务也不展示、也不发起查询"""
        svc, history_repo, client = _make_service([_progress()])
        history_repo.get_active_downloads.return_value = []

        result = svc.get_downloading_with_media_info()

        assert result == {"items": [], "total": 0}
        client.get_downloading_progress.assert_not_called()

    def test_disabled_downloader_skipped(self):
        """未启用的下载器不参与查询"""
        svc, _repo, client = _make_service([], downloader_enabled=0)

        result = svc.get_downloading_with_media_info()

        assert result["items"] == []
        client.get_downloading_progress.assert_not_called()

    def test_other_torrent_in_downloader_not_shown(self):
        """下载器里其它任务（非平台推送）不会出现——查询本身就只按我们的 hash"""
        svc, _repo, client = _make_service([_progress(), _progress(task_id="manual", name="Manual.mkv")])

        result = svc.get_downloading_with_media_info()

        assert [i["id"] for i in result["items"]] == [_PUSHED_HASH]


class TestStatusReconciliation:
    def test_completed_task_exits_and_marked(self):
        """进度达 100% → 退出列表并标记完成"""
        svc, history_repo, _client = _make_service([_progress(progress=100.0)])

        result = svc.get_downloading_with_media_info()

        assert result["items"] == []
        (updated,), _ = history_repo.batch_update_state.call_args
        assert updated == [("2", _PUSHED_HASH, "completed")]

    def test_missing_task_marked_completed_and_warned_once(self):
        """下载器里查不到（含 hash 不一致）→ 按完成处理并留痕一次，避免幽灵条目"""
        svc, history_repo, _client = _make_service([])

        with patch("app.services.download_service.log") as mock_log:
            result = svc.get_downloading_with_media_info()
            svc.get_downloading_with_media_info()
            svc.get_downloading_with_media_info()

        assert result["items"] == []
        (updated,), _ = history_repo.batch_update_state.call_args
        assert updated == [("2", _PUSHED_HASH, "completed")]
        assert mock_log.warn.call_count == 1, "同一任务重复轮询不应重复告警"

    def test_empty_result_logs_diagnostic_summary(self):
        """列表为空时输出诊断摘要，便于直接定位卡点"""
        svc, _repo, _client = _make_service([])

        with patch("app.services.download_service.log") as mock_log:
            svc.get_downloading_with_media_info()

        messages = [str(c) for c in mock_log.info.call_args_list]
        assert any("正在下载列表为空" in m for m in messages)


class TestPagination:
    def test_page_slice(self):
        """分页只作用于平台推送的任务集合"""
        svc, history_repo, _client = _make_service([_progress(), _progress(task_id="hash2", name="Second.mkv")])
        second = SimpleNamespace(
            downloader="2",
            download_id="hash2",
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
