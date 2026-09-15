"""qBittorrent 增量同步单元测试."""

from unittest.mock import MagicMock, patch

import pytest

from app.downloader.client.qbittorrent import Qbittorrent


class TestQbittorrentSync:
    """测试 qBittorrent sync/maindata 增量逻辑."""

    @pytest.fixture
    def client(self):
        with patch.object(Qbittorrent, "connect"):
            with patch.object(Qbittorrent, "init_torrent_management"):
                with patch("qbittorrentapi.Client") as mock_qbc_cls:
                    mock_qbc = MagicMock()
                    mock_qbc_cls.return_value = mock_qbc
                    qb = Qbittorrent(
                        config={
                            "host": "127.0.0.1",
                            "port": "8080",
                            "username": "admin",
                            "password": "adminadmin",
                        }
                    )
                    qb.qbc = mock_qbc
                    qb.download_dir = [{"save_path": "/downloads", "container_path": "/downloads"}]
                    return qb, mock_qbc

    def test_get_torrents_uses_sync_for_completed(self, client):
        """获取已完成任务且无 ids 时使用 sync_maindata."""
        qb, mock_qbc = client
        mock_qbc.sync_maindata.return_value = {
            "rid": 1,
            "full_update": True,
            "torrents": {
                "hash1": {
                    "name": "movie.mkv",
                    "state": "uploading",
                    "tags": "WOLFNAS",
                    "save_path": "/downloads",
                    "content_path": "/downloads/movie.mkv",
                    "total_size": 1000,
                    "progress": 1.0,
                    "dlspeed": 0,
                    "upspeed": 100,
                }
            },
        }

        torrents, error = qb.get_torrents(status="completed")

        assert not error
        assert len(torrents) == 1
        assert torrents[0].id == "hash1"
        assert torrents[0].labels == ["WOLFNAS"]
        assert qb._sync_rid == 1

    def test_get_torrents_sync_filter_by_tag(self, client):
        """sync 结果按标签过滤."""
        qb, mock_qbc = client
        mock_qbc.sync_maindata.return_value = {
            "rid": 2,
            "full_update": True,
            "torrents": {
                "hash1": {"name": "a.mkv", "state": "uploading", "tags": "WOLFNAS"},
                "hash2": {"name": "b.mkv", "state": "uploading", "tags": "other"},
            },
        }

        torrents, error = qb.get_torrents(status="completed", tag="WOLFNAS")

        assert not error
        assert len(torrents) == 1
        assert torrents[0].id == "hash1"

    def test_get_torrents_sync_incremental_update(self, client):
        """增量更新合并到本地快照."""
        qb, mock_qbc = client
        qb._sync_torrents = {"hash1": {"name": "old.mkv", "state": "uploading", "tags": "WOLFNAS"}}
        qb._sync_rid = 1
        mock_qbc.sync_maindata.return_value = {
            "rid": 2,
            "full_update": False,
            "torrents": {"hash2": {"name": "new.mkv", "state": "uploading", "tags": "WOLFNAS"}},
            "torrents_removed": ["hash1"],
        }

        torrents, error = qb.get_torrents(status="completed")

        assert not error
        assert len(torrents) == 1
        assert torrents[0].id == "hash2"
        assert "hash1" not in qb._sync_torrents

    def test_get_torrents_sync_incremental_update_preserves_name(self, client):
        """增量更新未携带 name 时，保留本地快照中的 name."""
        qb, mock_qbc = client
        qb._sync_torrents = {"hash1": {"name": "movie.mkv", "state": "uploading", "tags": "WOLFNAS"}}
        qb._sync_rid = 1
        mock_qbc.sync_maindata.return_value = {
            "rid": 2,
            "full_update": False,
            "torrents": {"hash1": {"state": "uploading", "tags": "WOLFNAS,已整理"}},
        }

        torrents, error = qb.get_torrents(status="completed")

        assert not error
        assert len(torrents) == 1
        assert torrents[0].id == "hash1"
        assert torrents[0].name == "movie.mkv"
        assert torrents[0].labels == ["WOLFNAS", "已整理"]

    def test_get_torrents_sync_excludes_incomplete_states(self, client):
        """sync 结果排除非已完成状态."""
        qb, mock_qbc = client
        mock_qbc.sync_maindata.return_value = {
            "rid": 1,
            "full_update": True,
            "torrents": {
                "hash1": {"name": "a.mkv", "state": "uploading", "tags": ""},
                "hash2": {"name": "b.mkv", "state": "downloading", "tags": ""},
            },
        }

        torrents, error = qb.get_torrents(status="completed")

        assert not error
        assert len(torrents) == 1
        assert torrents[0].id == "hash1"

    def test_get_torrents_sync_fallback_on_exception(self, client):
        """sync 失败时回退到 torrents_info."""
        qb, mock_qbc = client
        mock_qbc.sync_maindata.side_effect = Exception("sync error")
        mock_torrent = MagicMock()
        mock_torrent.hash = "hash1"
        mock_torrent.name = "movie.mkv"
        mock_torrent.size = 1000
        mock_torrent.state = "uploading"
        mock_torrent.tags = "WOLFNAS"
        mock_torrent.save_path = "/downloads"
        mock_torrent.content_path = "/downloads/movie.mkv"
        mock_torrent.progress = 1.0
        mock_torrent.dlspeed = 0
        mock_torrent.upspeed = 100
        mock_torrent.category = ""
        mock_torrent.tracker = ""
        mock_qbc.torrents_info.return_value = [mock_torrent]

        with patch.object(qb, "torrent_properties", return_value=MagicMock(id="hash1", labels=["WOLFNAS"])):
            torrents, error = qb.get_torrents(status="completed")

        assert not error
        assert len(torrents) == 1
        assert qb._sync_rid == 0

    def test_get_transfer_task_returns_paths(self, client):
        """get_transfer_task 返回标准化路径."""
        qb, mock_qbc = client
        mock_qbc.sync_maindata.return_value = {
            "rid": 1,
            "full_update": True,
            "torrents": {
                "hash1": {
                    "name": "movie.mkv",
                    "state": "uploading",
                    "tags": "WOLFNAS",
                    "save_path": "/downloads",
                    "content_path": "/downloads/movie.mkv",
                    "total_size": 1000,
                    "progress": 1.0,
                    "dlspeed": 0,
                    "upspeed": 100,
                }
            },
        }

        tasks = qb.get_transfer_task(tag="WOLFNAS")

        assert len(tasks) == 1
        assert tasks[0]["id"] == "hash1"
        assert tasks[0]["path"] == "/downloads/movie.mkv"


class TestQbittorrentAddTorrent:
    """qBittorrent 添加任务：传入下载目录时必须尊重该目录."""

    @pytest.fixture
    def client(self):
        with patch.object(Qbittorrent, "connect"):
            with patch.object(Qbittorrent, "init_torrent_management"):
                with patch("qbittorrentapi.Client") as mock_qbc_cls:
                    mock_qbc = MagicMock()
                    mock_qbc_cls.return_value = mock_qbc
                    qb = Qbittorrent(
                        config={
                            "host": "127.0.0.1",
                            "port": "8080",
                            "username": "admin",
                            "password": "adminadmin",
                            "torrent_management": "auto",
                        }
                    )
                    qb.qbc = mock_qbc
                    return qb, mock_qbc

    def test_add_torrent_honors_download_dir(self, client):
        """即使下载器配置了自动管理，传入 download_dir 也必须强制 is_auto=False 并透传 save_path."""
        qb, mock_qbc = client
        mock_qbc.torrents_add.return_value = "Ok."
        ret = qb.add_torrent(
            content=b"torrent-bytes",
            download_dir="/做种2",
        )
        assert ret is True
        _, kwargs = mock_qbc.torrents_add.call_args
        assert kwargs.get("save_path") == "/做种2"
        assert kwargs.get("use_auto_torrent_management") is False

    def test_add_torrent_ok_legacy_string(self, client):
        """旧版 qBittorrent 返回 'Ok.' 字符串."""
        qb, mock_qbc = client
        mock_qbc.torrents_add.return_value = "Ok."
        assert qb.add_torrent(content=b"torrent-bytes") is True

    def test_add_torrent_ok_metadata_success_count(self, client):
        """qBittorrent 5.2+ 返回 TorrentsAddedMetadata(success_count>0)."""
        qb, mock_qbc = client
        mock_qbc.torrents_add.return_value = MagicMock(success_count=1)
        assert qb.add_torrent(content=b"torrent-bytes") is True

    def test_add_torrent_fails_metadata_zero_success(self, client):
        """5.2+ 重复种子 success_count=0 视为失败."""
        qb, mock_qbc = client
        mock_qbc.torrents_add.return_value = MagicMock(success_count=0)
        assert qb.add_torrent(content=b"torrent-bytes") is False
        assert "success_count=0" in qb.get_last_add_error()

    def test_add_torrent_success_clears_last_error(self, client):
        qb, mock_qbc = client
        qb._set_last_add_error("旧错误")
        mock_qbc.torrents_add.return_value = MagicMock(success_count=1)
        assert qb.add_torrent(content=b"torrent-bytes") is True
        assert qb.get_last_add_error() == ""

    def test_fallback_connection_error_returns_empty(self, client):
        """qBittorrent 离线（ConnectionRefused）时回退接口应优雅返回空并标记异常."""
        qb, mock_qbc = client
        mock_qbc.torrents_info.side_effect = Exception("Connection refused")
        result, error = qb._fallback_get_torrents()
        assert result == []
        assert error is True

    def test_sync_connection_error_is_graceful(self, client):
        qb, mock_qbc = client
        mock_qbc.sync_maindata.side_effect = Exception("Connection refused")
        mock_qbc.torrents_info.side_effect = Exception("Connection refused")
        result, error = qb._get_torrents_sync(status="completed")
        assert result == []
        assert error is True

    def test_properties_403_reauthenticates_and_retries(self, client):
        import qbittorrentapi

        qb, mock_qbc = client
        mock_qbc.torrents_properties.side_effect = [
            qbittorrentapi.Forbidden403Error("Forbidden"),
            {"up_speed_avg": 5.0},
        ]
        mock_qbc.auth_log_in.return_value = None
        assert qb._get_torrent_generic_properties("hash1") == {"up_speed_avg": 5.0}
        mock_qbc.auth_log_in.assert_called_once()

    def test_properties_403_relogin_failure_returns_none(self, client):
        import qbittorrentapi

        qb, mock_qbc = client
        mock_qbc.torrents_properties.side_effect = qbittorrentapi.Forbidden403Error("Forbidden")
        mock_qbc.auth_log_in.side_effect = Exception("temporarily banned")
        assert qb._get_torrent_generic_properties("hash1") is None

    def test_fallback_403_reauthenticates(self, client):
        import qbittorrentapi

        qb, mock_qbc = client
        mock_qbc.torrents_info.side_effect = [qbittorrentapi.Forbidden403Error("Forbidden"), []]
        mock_qbc.auth_log_in.return_value = None
        result, error = qb._fallback_get_torrents()
        assert result == []
        assert error is False


class TestGetDownloadingTorrents:
    def test_get_downloading_excludes_completed(self):
        """已完成（progress=1，pausedUP 等）的任务不应计入正在下载数"""
        from app.downloader.client.qbittorrent import Qbittorrent
        from app.schemas.download import Torrent, TorrentStatus

        downloading = Torrent()
        downloading.progress = 0.5
        downloading.status = TorrentStatus.Downloading
        completed_paused = Torrent()
        completed_paused.progress = 1.0
        completed_paused.status = TorrentStatus.Paused

        qb = Qbittorrent.__new__(Qbittorrent)
        qb.qbc = MagicMock()
        with patch.object(Qbittorrent, "get_torrents", return_value=([downloading, completed_paused], False)):
            result = qb.get_downloading_torrents()
        assert result is not None
        assert len(result) == 1
        assert result[0].progress == 0.5

    def test_get_downloading_returns_none_on_error(self):
        from app.downloader.client.qbittorrent import Qbittorrent

        qb = Qbittorrent.__new__(Qbittorrent)
        qb.qbc = MagicMock()
        with patch.object(Qbittorrent, "get_torrents", return_value=([], True)):
            assert qb.get_downloading_torrents() is None


class TestMapStatusCoverage:
    """qb state 映射必须覆盖全部下载中状态。

    遗漏的状态会落到 Unknown，被 get_downloading_torrents 的状态白名单过滤，
    表现为"下载器里有任务、后端正在下载列表为空"，并被误判为已完成。
    """

    @pytest.mark.parametrize(
        "raw_state",
        [
            "downloading",
            "metaDL",  # 磁力/种子元数据下载中
            "forcedDL",
            "forcedMetaDL",
            "allocating",
        ],
    )
    def test_downloading_like_states(self, raw_state):
        from app.downloader.client.qbittorrent import Qbittorrent
        from app.schemas.download import TorrentStatus

        qb = Qbittorrent.__new__(Qbittorrent)
        assert qb._map_status(raw_state) == TorrentStatus.Downloading

    @pytest.mark.parametrize(
        "raw_state,expected_name",
        [
            ("stalledDL", "Pending"),
            ("queuedDL", "Queued"),
            ("queuedUP", "Queued"),
            ("uploading", "Uploading"),
            ("forcedUP", "Uploading"),
            ("checkingDL", "Checking"),
            ("checkingResumeData", "Checking"),
            ("moving", "Checking"),
            ("pausedUP", "Paused"),
            ("missingFiles", "Error"),
            ("error", "Error"),
        ],
    )
    def test_other_states(self, raw_state, expected_name):
        from app.downloader.client.qbittorrent import Qbittorrent
        from app.schemas.download import TorrentStatus

        qb = Qbittorrent.__new__(Qbittorrent)
        assert qb._map_status(raw_state) == getattr(TorrentStatus, expected_name)

    def test_meta_dl_not_filtered_as_missing(self):
        """metaDL 状态的任务必须能被 get_downloading_torrents 取到，而非当作不存在"""
        from app.downloader.client.qbittorrent import Qbittorrent
        from app.schemas.download import Torrent, TorrentStatus

        qb = Qbittorrent.__new__(Qbittorrent)
        qb.qbc = MagicMock()
        t = Torrent()
        t.progress = 0.0
        t.status = TorrentStatus.Downloading  # metaDL 映射后的结果
        with patch.object(Qbittorrent, "get_torrents", return_value=([t], False)):
            result = qb.get_downloading_torrents(ids=["hash1"])
        assert result is not None
        assert len(result) == 1


class TestDownloadingProgressFailureSemantics:
    """查询失败(None)必须与"无匹配任务"([])区分，否则下载器抖动会误标已完成"""

    def test_returns_none_when_query_fails(self):
        from app.downloader.client.qbittorrent import Qbittorrent

        qb = Qbittorrent.__new__(Qbittorrent)
        qb.qbc = MagicMock()
        with patch.object(Qbittorrent, "get_downloading_torrents", return_value=None):
            assert qb.get_downloading_progress(ids=["h1"]) is None

    def test_returns_empty_list_when_no_match(self):
        """查询成功但无匹配任务 → []（可安全判定任务已不存在）"""
        from app.downloader.client.qbittorrent import Qbittorrent

        qb = Qbittorrent.__new__(Qbittorrent)
        qb.qbc = MagicMock()
        with patch.object(Qbittorrent, "get_downloading_torrents", return_value=[]):
            assert qb.get_downloading_progress(ids=["h1"]) == []
