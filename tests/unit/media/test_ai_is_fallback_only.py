"""AI 识别只做兜底：规则能给出可信结果时绝不调用 LLM。

真实故障：LLM 作为主解析器时，同一批文件得到不一致的中文标题
（伟大的长征 / 天下长征 / 万里长征 / 长征），其中一个命中同名的其它作品，
同一部剧在媒体库里被拆成两个条目。规则解析是确定性的，同样的文件名永远
得到同样的结果，因此只要结果可信就不该让 LLM 介入。

这里的判定必须同时满足两个相反要求：
1. 正常命名一律可信 → 不触发 AI（否则等于没改）
2. 只解析出垃圾的才不可信 → 才触发 AI 兜底
"""

import pytest

from app.media.parser.regex import RegexParser
from app.media.service import MediaService


@pytest.fixture(scope="module")
def judge():
    return MediaService.__new__(MediaService)


@pytest.fixture(scope="module")
def parser():
    return RegexParser()


class TestNormalNamesNeverTriggerAi:
    @pytest.mark.parametrize(
        "name",
        [
            # 常规剧集
            "Show.Name.S02E05.1080p.WEB-DL.mkv",
            "某剧.S01E05.1080p.mkv",
            # 副标题含罗马数字（曾导致季号误判）
            "Delicious.in.Dungeon.S01E12.Episode.12.Red.Dragon.II.1080p.NF.WEB-DL.mkv",
            # 片名以数字开头（曾导致电影被判成剧集）
            "2.Insurgent.2015.ITA.UHD.Blu-ray.2160p.10bit.HDR.mkv",
            # 裸集号（E10 形式）
            "中华小当家.Cooking.Master.Boy.1997.E10.1080p.KKTV.WEB-DL.H264.AAC-PTerWEB.mp4",
            # 电影
            "Movie.Title.2019.1080p.BluRay.x264.mkv",
            # Season 关键字带点号
            "Show.Name.Season.2.Complete.1080p.mkv",
        ],
    )
    def test_reliable(self, judge, parser, name):
        parsed = parser.parse(name)

        assert judge._is_reliable_parse(parsed) is True, (
            f"{name} 的规则解析结果应判为可信，否则会白白调用 AI"
        )

    def test_has_clean_title(self, judge, parser):
        """可信结果必须给出干净片名（不含发布会话残留）。"""
        parsed = parser.parse("The.Great.Long.March.2026.S01E12.2160p.iQ.WEB-DL.mkv")

        assert judge._is_reliable_parse(parsed) is True
        assert "2160p" not in (parsed.title_en or "").lower()
        assert "web" not in (parsed.title_en or "").lower()


class TestJunkTriggerAi:
    @pytest.mark.parametrize(
        "name",
        [
            "www.example.com.mkv",   # 纯站点名
            "1080p.WEB-DL.mkv",      # 只有发布信息
            "2160p.mkv",
            "",
        ],
    )
    def test_unreliable(self, judge, parser, name):
        parsed = parser.parse(name) if name else None

        assert judge._is_reliable_parse(parsed) is False, (
            f"{name!r} 规则解析不出片名，应交给 AI 兜底"
        )


class TestUnreliableIndices:
    def test_only_junk_is_selected(self, judge, parser):
        names = [
            "Show.Name.S01E05.1080p.mkv",
            "1080p.WEB-DL.mkv",
            "Movie.Title.2019.1080p.mkv",
            "",
        ]
        parsed_list = [parser.parse(n) if n else None for n in names]

        assert judge._unreliable_indices(parsed_list) == [1, 3]

    def test_all_good_means_no_ai_call(self, judge, parser):
        parsed_list = [
            parser.parse("Show.Alpha.S01E01.1080p.mkv"),
            parser.parse("Show.Beta.S01E02.1080p.mkv"),
        ]

        assert judge._unreliable_indices(parsed_list) == []


class TestTitleNoiseDetection:
    @pytest.mark.parametrize(
        "noisy_title",
        ["Show 2160p", "Movie WEB-DL", "Film x265", "Title BluRay", "Name DDP5.1"],
    )
    def test_release_noise_in_title_is_unreliable(self, judge, noisy_title):
        """片名里混进发布信息说明没切干净，交给 AI 重试。"""
        from app.media.parser.base import ParserResult

        parsed = ParserResult(title_en=noisy_title, type=None)

        assert judge._is_reliable_parse(parsed) is False
