"""季号不得被标题里的罗马数字覆盖。

真实故障：源 `Delicious.in.Dungeon.S01E12....Red.Dragon.II....` 被解析成
S02E12，S01E13 被解析成 S03E13。同一部剧因此在媒体库里凭空多出 Season 2 /
Season 3，每个季目录只有 1 个视频，且与 Season 1 里对应集数共用同一个 inode。

根因：解析季集的规则归属 episode 类别，却同时给出了 season 值；stop 只锁定
了 episode 类别，season 仍然裸露，于是后面的「罗马数字当季标」规则把
`Red.Dragon.II` 的 II 当成了第二季。
"""

import pytest

from app.media import meta_info


def parse(name):
    info = meta_info(title=name)
    seasons = info.get_season_list()
    episodes = info.get_episode_list()
    return (seasons[0] if seasons else None), (episodes[0] if episodes else None)


class TestSeasonNotOverriddenBySubtitleRoman:
    @pytest.mark.parametrize(
        ("name", "season", "episode"),
        [
            # 副标题里的罗马数字：真实故障文件名
            ("Show.S01E12.Episode.12.Red.Dragon.II.1080p.NF.WEB-DL.DDP.5.1.H.264-GRP.mkv", 1, 12),
            ("Show.S01E13.Episode.13.Red.Dragon.III.&.Good.Medicine.1080p.NF.WEB-DL.mkv", 1, 13),
            # 作品名后缀带罗马数字
            ("Love.in.the.Big.City.S01E06.Love.In.The.Big.City.II.1080p.NF.WEB-DL.mkv", 1, 6),
            # 其他季号同样不能被覆盖
            ("Show.S02E05.Title.III.1080p.WEB-DL.mkv", 2, 5),
            ("Show.S03E07.Title.IV.1080p.WEB-DL.mkv", 3, 7),
        ],
    )
    def test_explicit_season_wins(self, name, season, episode):
        assert parse(name) == (season, episode)

    def test_part_marker_is_not_season(self):
        assert parse("Show.S01E05.Part.II.1080p.WEB-DL.mkv") == (1, 5)

    def test_roman_still_works_without_sxxexx(self):
        """没有 SxxExx 时，罗马数字仍是有效的季标（动漫常见）。"""
        assert parse("Anime.II.1080p.BluRay.mkv")[0] == 2


class TestSeasonKeywordSeparators:
    @pytest.mark.parametrize(
        ("name", "season"),
        [
            ("Show.Name.Season.2.Complete.1080p.mkv", 2),
            ("Show_Name_Season_3_1080p.mkv", 3),
            ("Show.Name.Season-4-1080p.mkv", 4),
            ("Show Name Season 5 1080p.mkv", 5),
        ],
    )
    def test_separators_are_accepted(self, name, season):
        """发布名常把 Season 与数字用点/下划线/短横分隔，不能只认空格。"""
        assert parse(name)[0] == season

    def test_year_after_season_is_not_season(self):
        """`Season 2017` 是「片名 Season + 年份」，不是第 2017 季。"""
        assert parse("The.Long.Season.2017.1080p.mkv")[0] is None
