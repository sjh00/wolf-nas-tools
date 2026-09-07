"""DownloadService 下载前多版本检测 单元测试."""

from unittest.mock import MagicMock

from app.media.models import MediaInfo
from app.schemas.download import DownloadResultDTO
from app.services.download_service import DownloadService


def _make_svc(file_index=None, media=None, downloader=None):
    return DownloadService(
        downloader=downloader if downloader else MagicMock(),
        searcher=MagicMock(),
        media_service=media if media else MagicMock(),
        sites=MagicMock(),
        site_engine=MagicMock(),
        indexer_service=MagicMock(),
        torrent_remover=MagicMock(),
        download_history_repo=MagicMock(),
        file_index_service=file_index,
    )


def _media(tmdb_id=12345):
    m = MediaInfo()
    m.tmdb_id = tmdb_id
    m.title = "Test.2020.1080p"
    return m


class TestCheckMultiVersion:
    def test_no_tmdb_returns_none(self):
        svc = _make_svc(file_index=MagicMock())
        m = MediaInfo()
        m.tmdb_id = 0
        assert svc._check_multi_version(m) is None

    def test_no_file_index_returns_none(self):
        svc = _make_svc(file_index=None)
        assert svc._check_multi_version(_media()) is None

    def test_existing_two_versions_triggers_confirm(self):
        fi = MagicMock()
        fi.get_versions.return_value = [
            {"full_path": "/a.mkv", "exists": True},
            {"full_path": "/b.mkv", "exists": True},
        ]
        svc = _make_svc(file_index=fi)
        result = svc._check_multi_version(_media())
        assert result is not None
        assert result.need_confirm is True
        assert result.tmdb_id == 12345
        assert len(result.versions) == 2

    def test_single_existing_no_confirm(self):
        fi = MagicMock()
        fi.get_versions.return_value = [
            {"full_path": "/a.mkv", "exists": True},
            {"full_path": "/b.mkv", "exists": False},
        ]
        svc = _make_svc(file_index=fi)
        assert svc._check_multi_version(_media()) is None


class TestDownloadFromLinkConfirm:
    def test_need_confirm_blocks_downloader(self):
        """命中多版本时，不调用下载器，且返回 need_confirm。"""
        media = _media()
        fi = MagicMock()
        fi.get_versions.return_value = [
            {"full_path": "/a.mkv", "exists": True},
            {"full_path": "/b.mkv", "exists": True},
        ]
        down = MagicMock()
        svc = _make_svc(file_index=fi, downloader=down)
        svc._sites.get_sites.return_value = {}
        # 让 get_media_info 返回带 tmdb 的 media
        svc._media.get_media_info.return_value = media

        result = svc.download_from_link(
            site="s", enclosure="http://x", title="Test.2020.1080p", description="",
            page_url="", size="0", seeders="0", uploadvolumefactor="1",
            downloadvolumefactor="1", dl_dir="", dl_setting="", user_name="u",
        )
        assert result.need_confirm is True
        down.download.assert_not_called()

    def test_no_duplicate_normal_download(self):
        """无重复时正常推送下载器。"""
        media = _media()
        fi = MagicMock()
        fi.get_versions.return_value = []
        down = MagicMock()
        down.download.return_value = (None, True, "")
        svc = _make_svc(file_index=fi, downloader=down)
        svc._media.get_media_info.return_value = media

        result = svc.download_from_link(
            site="s", enclosure="http://x", title="Test.2020.1080p", description="",
            page_url="", size="0", seeders="0", uploadvolumefactor="1",
            downloadvolumefactor="1", dl_dir="", dl_setting="", user_name="u",
        )
        assert result.success is True
        down.download.assert_called_once()
