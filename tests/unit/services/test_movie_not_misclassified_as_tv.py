"""片名以数字开头的电影不能被判成剧集。

真实故障：`2.Insurgent.2015...`（《分歧者2：绝地反击》）、
`20.Once.Again.2015...`（《重返20岁》）这类文件名开头的数字被当成集号，
媒体类型随之判成剧集，于是同一部电影在 TV 库里出现一份
`纪录片/X (某年)/Season 1/...S01E02...`，与电影库里的正确副本共用 inode。
"""

import pytest

from app.media import meta_info


def parse(name):
    info = meta_info(title=name)
    seasons = info.get_season_list()
    episodes = info.get_episode_list()
    return info.get_name(), (seasons[0] if seasons else None), (episodes[0] if episodes else None)


class TestLeadingNumberIsTitleNotEpisode:
    @pytest.mark.parametrize(
        ("name", "title"),
        [
            ("2.Insurgent.2015.ITA.UHD.Blu-ray.2160p.mkv", "2 Insurgent"),
            ("20.Once.Again.2015.2160p.WEB-DL.mkv", "20 Once Again"),
            ("12.Angry.Men.1957.1080p.BluRay.mkv", "12 Angry Men"),
            ("7.Pounds.2008.1080p.BluRay.mkv", "7 Pounds"),
            ("3.Idiots.2009.1080p.mkv", "3 Idiots"),
            ("8.Mile.2002.1080p.mkv", "8 Mile"),
        ],
    )
    def test_no_episode_and_title_keeps_number(self, name, title):
        got_title, season, episode = parse(name)

        assert episode is None, "开头的数字是片名的一部分，不是集号"
        assert got_title == title, "数字必须留在片名里，否则 TMDB 查不到"

    def test_real_movie_with_year_still_matches(self):
        """《1917》这类纯数字片名同样不该产生集号。"""
        assert parse("1917.2019.2160p.BluRay.x265.mkv")[2] is None


class TestBareEpisodeStillWorks:
    @pytest.mark.parametrize(
        ("name", "episode"),
        [
            ("某剧 05.mkv", 5),
            ("剧名 12.mkv", 12),
            ("Show 05 1080p.mkv", 5),
            ("[Group] 剧名 - 05 [1080p].mkv", 5),
        ],
    )
    def test_bare_episode_after_title_still_detected(self, name, episode):
        assert parse(name)[2] == episode

    @pytest.mark.parametrize(
        ("name", "season", "episode"),
        [
            ("1923.S01E05.1080p.mkv", 1, 5),
            ("1883.S01E01.1080p.mkv", 1, 1),
            ("9-1-1.S01E05.1080p.mkv", 1, 5),
            ("The.100.S01E05.1080p.mkv", 1, 5),
        ],
    )
    def test_digit_leading_show_name_still_parsed(self, name, season, episode):
        """以数字开头的剧名靠 SxxExx 识别，不受本次改动影响。"""
        assert parse(name)[1:] == (season, episode)
