"""季号 0（TMDB 特别篇）必须落到 extras/，不能生成 Season 0。

真实故障：豪斯医生的 S08 特别篇在 TV 库里落成
`豪斯医生 (2004)/Season 0/怪医豪斯 - S00E05 - 第5集.mkv`，
和正片并列在同一个剧目录下。约定是特别篇一律进 extras/。
"""

from app.domain.media_types import ProviderMediaType
from app.media.models import MediaInfo
from app.services.transfer.path_resolver import TransferPathResolver, extras_sp_label


def _resolver():
    return TransferPathResolver(
        movie_path=["/media/movie"],
        tv_path=["/media/tv"],
        anime_path=["/media/anime"],
        movie_dir_rmt_format="{title} ({year})",
        movie_file_rmt_format="{title}",
        tv_dir_rmt_format="{title} ({year})",
        tv_season_rmt_format="Season {season}",
        tv_file_rmt_format="{title} - S{season:02d}E{episode:02d}",
        movie_category_flag=True,
        tv_category_flag=True,
        anime_category_flag=True,
    )


def _tv(season, episode=1, note=None, title="示例剧"):
    return MediaInfo(
        type=ProviderMediaType.SERIES,
        title=title,
        year="2004",
        begin_season=season,
        begin_episode=episode,
        end_episode=episode,
        note=note or {},
        org_string=f"{title}.S{season:02d}E{episode:02d}.mkv",
        rev_string=f"{title}.S{season:02d}E{episode:02d}.mkv",
    )


class TestSeasonZeroIsExtras:
    def test_season_zero_lands_in_extras(self):
        _dir, season_name, _file = _resolver().get_tv_dest_path(_tv(0, 5))

        assert season_name == "extras", "TMDB 第 0 季是特别篇，必须进 extras"

    def test_episode_zero_lands_in_extras(self):
        """`Show.S03E00.Special...` 这类集号为 0 的特别篇也不能留在正片季里。"""
        _dir, season_name, _file = _resolver().get_tv_dest_path(_tv(3, 0))

        assert season_name == "extras", "集号 0 是特别篇写法，不能生成 S03E00"

    def test_season_one_stays_normal(self):
        _dir, season_name, _file = _resolver().get_tv_dest_path(_tv(1, 1))

        assert season_name == "Season 1"

    def test_season_two_stays_normal(self):
        _dir, season_name, _file = _resolver().get_tv_dest_path(_tv(2, 3))

        assert season_name == "Season 2"

    def test_explicit_extras_note_still_wins(self):
        _dir, season_name, _file = _resolver().get_tv_dest_path(
            _tv(1, 9, note={"is_extras": True})
        )

        assert season_name == "extras"


class TestExtrasSpLabel:
    def test_sp_label_from_filename(self):
        assert extras_sp_label("The.World.at.War.SP09.1973.BluRay.mkv") == "SP09"

    def test_no_label_returns_empty(self):
        assert extras_sp_label("Show.S01E05.1080p.mkv") == ""
