"""DownloadCore.check_exists_medias 返回结构与季号键兼容性测试."""

from unittest.mock import MagicMock, patch

import pytest

from app.domain.mediatypes import MediaType
from app.services.download_core import DownloadCore


class _Meta:
    def __init__(self, **kwargs):
        self.type = kwargs.get("type", MediaType.TV)
        self.tmdb_id = kwargs.get("tmdb_id", 100)
        self.total_episodes = kwargs.get("total_episodes", None)
        self._season = kwargs.get("season", "1")

    def get_season_seq(self):
        return self._season


@pytest.fixture
def core():
    with patch("app.services.download_core.DownloadPipeline"):
        c = DownloadCore(
            client_factory=MagicMock(),
            message=MagicMock(),
            mediaserver=MagicMock(),
            filetransfer=MagicMock(),
            sites=MagicMock(),
            siteconf=MagicMock(),
            sitesubtitle=MagicMock(),
            event_bus=MagicMock(),
            download_repo=MagicMock(),
            download_setting_repo=MagicMock(),
            systemconfig=MagicMock(),
            downloader_repo=MagicMock(),
            site_engine=MagicMock(),
        )
        return c


class TestCheckExistsMedias:
    def test_tv_int_season_key_in_total_ep(self, core):
        meta = _Meta(season="1", tmdb_id=42)
        core._filetransfer.get_no_exists_medias.return_value = [2, 3]

        exist, no_exists, _ = core.check_exists_medias(meta, total_ep={1: 10})

        assert exist is False
        assert 42 in no_exists
        assert no_exists[42][0]["season"] == 1
        assert no_exists[42][0]["episodes"] == [2, 3]
        assert no_exists[42][0]["total_episodes"] == 10
        # 传给 existence checker 的 season 为 int
        kwargs = core._filetransfer.get_no_exists_medias.call_args
        assert kwargs[1].get("season") == 1 or kwargs[0][1] == 1 or kwargs.kwargs.get("season") == 1

    def test_tv_complete_returns_true(self, core):
        meta = _Meta(season="1", tmdb_id=7)
        core._filetransfer.get_no_exists_medias.return_value = []

        exist, no_exists, _ = core.check_exists_medias(meta, total_ep={"1": 8})

        assert exist is True
        assert no_exists == {}

    def test_movie_exists(self, core):
        meta = _Meta(type=MediaType.MOVIE, tmdb_id=9)
        core._filetransfer.get_no_exists_medias.return_value = [{"title": "X"}]

        exist, no_exists, _ = core.check_exists_medias(meta)
        assert exist is True
        assert no_exists == {}
