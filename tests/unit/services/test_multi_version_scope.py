"""多版本检测必须按「同一季同一集」判定。

真实问题：添加一部连载剧的新集时弹出「检测到多个已入库的版本」，
因为检测只按 tmdb_id 取回整部剧的所有历史记录——对连载剧而言几乎必然
>2 条，于是每次加新集都误报。

「多版本」的业务含义是**同一集存在多份不同规格的文件**（换版），
不同集之间不构成多版本。
"""

from unittest.mock import MagicMock

from app.domain.media_types import ProviderMediaType
from app.media.models import MediaInfo
from app.services.download_service import DownloadService


def _service(versions):
    svc = DownloadService.__new__(DownloadService)
    svc._file_index = MagicMock()
    svc._file_index.get_versions.return_value = versions
    return svc

def _tv(season: int, episode: int) -> MediaInfo:
    media = MediaInfo()
    media.type = ProviderMediaType.SERIES
    media.tmdb_id = 100
    media.begin_season = season
    media.begin_episode = episode
    return media

def _ver(season_episode: str, spec: str = "1080p", exists: bool = True) -> dict:
    return {
        "season_episode": season_episode,
        "spec": spec,
        "exists": exists,
        "full_path": f"/media/{season_episode}-{spec}.mkv",
        "dest_filename": f"{season_episode}-{spec}.mkv",
    }

class TestSeasonEpisodeKey:
    def test_parses_common_formats(self):
        key = DownloadService._season_episode_key
        assert key("S01 E50") == (1, 50)
        assert key("S01E50") == (1, 50)
        assert key("s2e7") == (2, 7)
        assert key("S01") == (1, 0)

    def test_returns_none_without_season(self):
        assert DownloadService._season_episode_key("") is None
        assert DownloadService._season_episode_key(None) is None

class TestMultiVersionScope:
    def test_tv_with_episodes_returns_scope(self):
        svc = _service([])
        assert svc._multi_version_scope(_tv(1, 50)) == {(1, 50)}

    def test_movie_has_no_scope(self):
        svc = _service([])
        media = MediaInfo()
        media.type = ProviderMediaType.MOVIE
        media.tmdb_id = 1
        assert svc._multi_version_scope(media) is None

    def test_tv_without_episodes_has_no_scope(self):
        svc = _service([])
        media = MediaInfo()
        media.type = ProviderMediaType.SERIES
        media.tmdb_id = 1
        assert svc._multi_version_scope(media) is None

class TestCheckMultiVersion:
    def test_different_episodes_do_not_trigger(self):
        """核心回归：整部剧有大量历史，但新增集的集号不同 → 不应要求确认。"""
        svc = _service(
            [
                _ver("S01 E01"),
                _ver("S01 E02"),
                _ver("S01 E03"),
                _ver("S01 E49"),
            ]
        )
        assert svc._check_multi_version(_tv(1, 50)) is None

    def test_same_episode_two_specs_triggers(self):
        """同一集两份不同规格 → 才需要确认换版。"""
        svc = _service([_ver("S01 E50", "1080p"), _ver("S01 E50", "2160p")])
        result = svc._check_multi_version(_tv(1, 50))
        assert result is not None
        assert result.need_confirm is True
        assert len(result.versions) == 2
        assert all("S01 E50" in v["season_episode"] for v in result.versions)

    def test_same_episode_one_spec_no_trigger(self):
        svc = _service([_ver("S01 E50", "1080p")])
        assert svc._check_multi_version(_tv(1, 50)) is None

    def test_missing_files_ignored(self):
        svc = _service(
            [
                _ver("S01 E50", "1080p", exists=False),
                _ver("S01 E50", "2160p", exists=True),
            ]
        )
        assert svc._check_multi_version(_tv(1, 50)) is None

    def test_tv_without_episode_info_does_not_trigger(self):
        """拿不到季集就不拦，否则连载剧加新集必被误报。"""
        svc = _service([_ver("S01 E01"), _ver("S01 E02"), _ver("S01 E03")])
        media = MediaInfo()
        media.type = ProviderMediaType.SERIES
        media.tmdb_id = 100
        assert svc._check_multi_version(media) is None

    def test_movie_still_counts_whole_work(self):
        svc = _service([_ver("", "1080p"), _ver("", "2160p")])
        media = MediaInfo()
        media.type = ProviderMediaType.MOVIE
        media.tmdb_id = 1
        result = svc._check_multi_version(media)
        assert result is not None
        assert result.need_confirm is True

    def test_no_tmdb_id_skips(self):
        svc = _service([_ver("S01 E50", "1080p"), _ver("S01 E50", "2160p")])
        media = _tv(1, 50)
        media.tmdb_id = None  # type: ignore[assignment]
        assert svc._check_multi_version(media) is None

    def test_no_file_index_skips(self):
        svc = DownloadService.__new__(DownloadService)
        svc._file_index = None
        assert svc._check_multi_version(_tv(1, 50)) is None

    def test_season_pack_counts_each_episode(self):
        """整季包（多集）时，任一集存在多版本都应提示。"""
        svc = _service(
            [
                _ver("S01 E01", "1080p"),
                _ver("S01 E01", "2160p"),
                _ver("S01 E02", "1080p"),
            ]
        )
        media = MediaInfo()
        media.type = ProviderMediaType.SERIES
        media.tmdb_id = 100
        media.begin_season = 1
        media.begin_episode = 1
        media.end_episode = 2
        result = svc._check_multi_version(media)
        assert result is not None
        # 返回该季包范围内全部已入库版本（含单版本集），便于用户一并选择
        assert len(result.versions) == 3
        assert {v["season_episode"] for v in result.versions} == {"S01 E01", "S01 E02"}
