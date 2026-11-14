"""片名残留修复：@ 组名 / 2in1 / Pad-HDR / friDay 平台与 Friday 片名.

这些是生产未识别清单里暴露的通用缺陷，用占位式片名覆盖边界，
不引入真实影视作品信息。
"""

import pytest

from app.media.parser.unified import UnifiedParser

AT_GROUP = "Some.Title.1958.1080p.BluRay.Remux.AVC.DTS-HD.MA.2.0.Sample@GRP"
AT_GROUP_AFTER_AUDIO = "Other.Title.1957.1080p.BluRay.Remux.AVC.DTS-HD.MA.2.0.Sample@GRP"
PACK_TAG = "Demo.Movie.2007.2in1.BluRay.1080p.x264-10bit.TrueHD-GRP"
PAD_HDR = "Placeholder.Title.1993.1080p.Pad-HDR.UHD.BluRay.AAC.2Audio.x265-10bit-GRPX"
PLATFORM_FRIDAY = "Demo.Series.2026.S01.1080p.FRIDAY.WEB-DL.AAC2.0.H.264-DepWeb"


@pytest.fixture(scope="module")
def parser():
    return UnifiedParser()


class TestReleaseGroupAtSuffix:
    """点分隔的「组名@站点」尾部标签必须剥离，不能并进片名."""

    def test_dot_separated_at_group(self, parser):
        result = parser.parse(AT_GROUP)
        assert result is not None
        assert result.title_en == "Some Title"

    def test_at_group_after_audio_codec(self, parser):
        result = parser.parse(AT_GROUP_AFTER_AUDIO)
        assert result is not None
        assert result.title_en == "Other Title"

    def test_at_group_is_recorded(self, parser):
        result = parser.parse(AT_GROUP)
        assert result is not None
        assert result.resource_team == "Sample@GRP"


class TestCollectionPackTag:
    """2in1 / 3in1 是多片合一装帧标签，不属于片名."""

    def test_2in1_stripped(self, parser):
        result = parser.parse(PACK_TAG)
        assert result is not None
        assert result.title_en == "Demo Movie"

    def test_year_still_kept(self, parser):
        result = parser.parse(PACK_TAG)
        assert result is not None
        assert result.year == "2007"


class TestPadHdrTag:
    """Pad-HDR 是华语 PT 的「自带 HDR」标记；拆词后会残留 Pad."""

    def test_pad_hdr_not_in_title(self, parser):
        result = parser.parse(PAD_HDR)
        assert result is not None
        assert result.title_en == "Placeholder Title"


class TestFridayPlatformVsTitle:
    """friDay 是台湾平台（固定写作 friDay），Friday 是常用片名词."""

    def test_platform_after_metadata_stripped(self, parser):
        result = parser.parse(PLATFORM_FRIDAY)
        assert result is not None
        assert result.title_en == "Demo Series"

    def test_title_word_friday_kept(self, parser):
        result = parser.parse("My.Fake.Friday.1951.1080p.BluRay.Remux.AVC.DTS-HD.MA.2.0-GRP")
        assert result is not None
        assert result.title_en == "My Fake Friday"

    def test_title_only_friday_kept(self, parser):
        result = parser.parse("Friday.1995.1080p.BluRay.x264-GRP")
        assert result is not None
        assert result.title_en == "Friday"

    def test_friday_inside_title_kept(self, parser):
        result = parser.parse("The.Fictional.Friday.1940.1080p.BluRay.x264")
        assert result is not None
        assert result.title_en == "The Fictional Friday"
