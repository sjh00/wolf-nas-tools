"""扫库找已存在集数：订阅新增时用它推导起始进度。

真实故障：新订阅只按「转移历史/下载记录」推导进度，媒体库里早就有整季文件
（手工放入或旧版本入库）时进度仍是 0，于是重复下载。分类在订阅创建时可能还
没解析出来，所以扫库不能只认一个分类目录。
"""

import os

from app.domain.media_types import ProviderMediaType
from app.media import meta_info
from app.media.models import MediaInfo
from app.services.transfer.existence_checker import MediaExistenceChecker
from app.services.transfer.path_resolver import TransferPathResolver

TITLE = "示例剧集"
YEAR = "2026"


def _resolver(tv_root="/media/tv", tv_flag=True, anime_flag=False):
    return TransferPathResolver(
        movie_path=["/media/movie"],
        tv_path=[tv_root],
        anime_path=["/media/anime"],
        movie_dir_rmt_format="{title} ({year})",
        movie_file_rmt_format="{title}",
        tv_dir_rmt_format="{title} ({year})",
        tv_season_rmt_format="Season {season}",
        tv_file_rmt_format="{title} - S{season:02d}E{episode:02d}",
        movie_category_flag=False,
        tv_category_flag=tv_flag,
        anime_category_flag=anime_flag,
    )


def _tv(category="", episode=None, title=TITLE):
    info = MediaInfo(
        type=ProviderMediaType.SERIES,
        category=category,
        title=title,
        year=YEAR,
        begin_season=1,
    )
    if episode is not None:
        info.begin_episode = episode
        info.end_episode = episode
        info.org_string = f"{title}.S01E{episode:02d}.mkv"
        info.rev_string = info.org_string
    return info


def _mk(path: str, name: str) -> None:
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, name), "w", encoding="utf-8") as fh:
        fh.write("x")


def _checker(root: str, tv_flag=True):
    # 扫库读的是 resolver 里配置的库路径，不是调用时传入的 root
    return MediaExistenceChecker(_resolver(tv_root=root, tv_flag=tv_flag))


class TestFindSeasonEpisodes:
    def test_finds_episodes_in_category_dir_without_knowing_category(self, tmp_path):
        """核心：分类未知时也要在「根/分类/剧名/Season N」里找到已入库集数。"""
        season_dir = tmp_path / "tv" / "国产剧" / f"{TITLE} ({YEAR})" / "Season 1"
        for ep in (1, 2, 3):
            _mk(str(season_dir), f"{TITLE} - S01E{ep:02d}.mkv")

        found = _checker(str(tmp_path / "tv")).find_season_episodes(
            _tv(), meta_info, 1
        )

        assert found == {1, 2, 3}

    def test_finds_episodes_in_flat_dir(self, tmp_path):
        season_dir = tmp_path / "tv" / f"{TITLE} ({YEAR})" / "Season 1"
        _mk(str(season_dir), f"{TITLE} - S01E01.mkv")

        found = _checker(str(tmp_path / "tv")).find_season_episodes(
            _tv(), meta_info, 1
        )

        assert found == {1}

    def test_ignores_other_shows_and_other_seasons(self, tmp_path):
        root = tmp_path / "tv"
        own = root / "国产剧" / f"{TITLE} ({YEAR})" / "Season 1"
        _mk(str(own), f"{TITLE} - S01E01.mkv")
        other_show = root / "国产剧" / f"另一部剧 ({YEAR})" / "Season 1"
        _mk(str(other_show), "另一部剧 - S01E09.mkv")
        other_season = root / "国产剧" / f"{TITLE} ({YEAR})" / "Season 2"
        _mk(str(other_season), f"{TITLE} - S02E05.mkv")

        found = _checker(str(root)).find_season_episodes(_tv(), meta_info, 1)

        assert found == {1}

    def test_missing_dir_returns_empty(self, tmp_path):
        found = _checker(str(tmp_path / "tv")).find_season_episodes(
            _tv(), meta_info, 1
        )

        assert found == set()

    def test_movie_has_no_episodes(self, tmp_path):
        movie = MediaInfo(
            type=ProviderMediaType.MOVIE,
            title=TITLE,
            year=YEAR,
            org_string=f"{TITLE}.{YEAR}.mkv",
            rev_string=f"{TITLE}.{YEAR}.mkv",
        )

        found = _checker(str(tmp_path / "tv")).find_season_episodes(
            movie, meta_info, 1
        )

        assert found == set()


class TestNoExistsStillConsistent:
    def test_get_no_exists_medias_uses_same_episode_parsing(self, tmp_path):
        """重构后旧接口行为不变：已存在 1、2 集 → 缺失 3..10。"""
        season_dir = tmp_path / "tv" / "国产剧" / f"{TITLE} ({YEAR})" / "Season 1"
        for ep in (1, 2):
            _mk(str(season_dir), f"{TITLE} - S01E{ep:02d}.mkv")

        raw = _checker(str(tmp_path / "tv")).get_no_exists_medias(
            _tv(category="国产剧"), meta_info, season=1, total_num=10
        )
        missing = sorted(int(ep) for ep in raw if isinstance(ep, int))

        assert missing == list(range(3, 11))

    def test_all_episodes_present_returns_empty_missing(self, tmp_path):
        season_dir = tmp_path / "tv" / "国产剧" / f"{TITLE} ({YEAR})" / "Season 1"
        for ep in range(1, 5):
            _mk(str(season_dir), f"{TITLE} - S01E{ep:02d}.mkv")

        missing = _checker(str(tmp_path / "tv")).get_no_exists_medias(
            _tv(category="国产剧"), meta_info, season=1, total_num=4
        )

        assert missing == []
