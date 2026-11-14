"""片名尾部的续集编号（Demo Movie 2 / Demo Runner 2049 / Part II）.

发行名里「片名+续集号+出品年」与「裸集号」形态一致，只有数字后面跟的是
年还是分辨率/来源能区分。判错会把电影算成剧集：下错下载分类 → 落错盘 →
媒体库再跨盘复制一份；同时片名退化成原作，元数据匹配到错作品。
"""

import pytest

from app.media.parser.unified import UnifiedParser


@pytest.fixture(scope="module")
def parser():
    return UnifiedParser()


class TestSequelNumberKept:
    @pytest.mark.parametrize(
        ("raw", "expected_title", "expected_year"),
        [
            ("Demo Movie 2 2020 RERiP 1080p BluRay x264 DTS-GRP", "Demo Movie 2", "2020"),
            ("Demo.Movie.2.2020.RERiP.1080p.BluRay.x264.DTS-GRP", "Demo Movie 2", "2020"),
            ("Le Film 2 1982 1080p ITA BluRay AVC LPCM 2.0-DiY@GRP", "Le Film 2", "1982"),
            ("Demo Story 2 1999.1080p.BluRay.x264", "Demo Story 2", "1999"),
            ("Demo Runner 2049 2017 2160p UHD BluRay", "Demo Runner 2049", "2017"),
            ("A Demo Saga Part 1 1995 BluRay 1080p", "A Demo Saga Part 1", "1995"),
            ("Demo Saga Part II 1974 1080p BluRay x264", "Demo Saga Part II", "1974"),
        ],
    )
    def test_title_keeps_sequel_number(self, parser, raw, expected_title, expected_year):
        result = parser.parse(raw)
        assert result is not None
        assert result.title_en == expected_title
        assert result.year == expected_year

    @pytest.mark.parametrize(
        "raw",
        [
            "Demo Movie 2 2020 RERiP 1080p BluRay x264 DTS-GRP",
            "Demo.Movie.2.2020.RERiP.1080p.BluRay.x264.DTS-GRP",
            "Le Film 2 1982 1080p ITA BluRay AVC LPCM 2.0-DiY@GRP",
            "Demo Story 2 1999.1080p.BluRay.x264",
            "Demo Runner 2049 2017 2160p UHD BluRay",
        ],
    )
    def test_sequel_not_treated_as_episode(self, parser, raw):
        """续集号不能被当成集号——否则类型变剧集、下错分类。"""
        result = parser.parse(raw)
        assert result is not None
        assert result.type.value == "movie"
        assert result.episode is None
        assert result.season is None


class TestRealEpisodeStillWorks:
    """真正的集号必须照旧识别，不能被续集规则误伤。"""

    @pytest.mark.parametrize(
        ("raw", "expected_ep"),
        [
            ("Some.Show.S01E05.1080p.WEB-DL", 5),
            ("Some Show - 05 [1080p][GRP]", 5),
            ("Some.Show.EP12.2019.1080p.WEB-DL", 12),
            ("Some.Show.第08集.1080p", 8),
        ],
    )
    def test_episode_detected(self, parser, raw, expected_ep):
        result = parser.parse(raw)
        assert result is not None
        assert result.episode == expected_ep
        assert result.type.value in ("tv", "anime")

    def test_tv_show_title_with_year(self, parser):
        """剧集名 + 出品年（无续集号）仍按剧集处理。"""
        result = parser.parse("Some.Show.S01.2020.1080p.WEB-DL")
        assert result is not None
        assert result.season == 1
        assert result.type.value in ("tv", "anime")


class TestPlainMovieUnaffected:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Some.Movie.2019.1080p.BluRay.x264", "Some Movie"),
            ("It.2017.1080p.BluRay.x264", "It"),
            ("Spider-Man.2002.1080p.BluRay.x264", "Spider-Man"),
            ("Demo.Film.2021.1080p.WEB-DL.DDP5.1.H.265-GRP", "Demo Film"),
        ],
    )
    def test_movie_title(self, parser, raw, expected):
        result = parser.parse(raw)
        assert result is not None
        assert result.title_en == expected
        assert result.type.value == "movie"
