"""片名短词保护：`Man`/`Us` 这类词不能被当成发布信息剥掉。

真实故障：`Spider-Man.2002.1080p.mkv` 被解析成 `Spider`、`The.Last.of.Us.S01E03`
被解析成 `The Last Of`。两处各有原因：

1. 发布组后缀正则无条件剥掉末尾 `-Word`，把 `-Man` 当成组名。
   真实发布组要么全大写（FRDS/CMCT）、要么大小写混排（NTb/PlayWEB）、要么带 @。
   「首字母大写 + 其余全小写」是典型英文词形态，属于片名。
2. 剥词循环把 `_HIGH_FREQ_TITLE_WORDS` 之外的 2 字母词当后缀，`Us` 不在表里。

两条都会让片名残缺，TMDB 随即搜不到正确作品，表现为未识别或错配。
"""

import pytest

from app.media import meta_info
from app.media.parser.unified.name_extractor import (
    _HIGH_FREQ_TITLE_WORDS,
    _looks_like_title_word,
)


def name_of(filename: str) -> str:
    return (meta_info(title=filename).get_name() or "").strip()


class TestTitleWordsSurvive:
    @pytest.mark.parametrize(
        ("filename", "expect"),
        [
            # 连字符后半段是片名（曾被当发布组）
            ("Spider-Man.2002.1080p.BluRay.mkv", "Spider-Man"),
            ("Spider-Man.No.Way.Home.2021.2160p.mkv", "Spider-Man No Way Home"),
            ("Wonder.Woman.1984.1080p.mkv", "Wonder Woman"),
            # 2 字母片名尾词（曾被当残留后缀）
            ("The.Last.of.Us.S01E03.2023.1080p.mkv", "The Last Of Us"),
            ("Us.2019.1080p.BluRay.mkv", "Us"),
            ("It.2017.1080p.mkv", "It"),
            ("Up.2009.1080p.mkv", "Up"),
            # 3 字母片名
            ("Men.2022.1080p.mkv", "Men"),
            ("Her.2013.1080p.mkv", "Her"),
        ],
    )
    def test_name_keeps_title_words(self, filename, expect):
        assert name_of(filename) == expect


class TestRealReleaseGroupsStillStripped:
    @pytest.mark.parametrize(
        ("filename", "expect"),
        [
            # 全大写
            ("Interstellar.2014.1080p.BluRay.x264-FRDS.mkv", "Interstellar"),
            ("Oppenheimer.2023.1080p.BluRay.x265-CMCT.mkv", "Oppenheimer"),
            # 大小写混排
            ("Breaking.Bad.S01E05.2008.2160p.WEB-DL-NTb.mkv", "Breaking Bad"),
            ("Frieren.S01E01.1080p-PlayWEB.mkv", "Frieren"),
            # 带 @ 站点
            ("Parasite.2019.2160p.UHD-DIY@UBits.mkv", "Parasite"),
        ],
    )
    def test_group_is_removed(self, filename, expect):
        assert name_of(filename) == expect


class TestLooksLikeTitleWord:
    @pytest.mark.parametrize("word", ["Man", "Woman", "Home", "Us"])
    def test_human_word_shape(self, word):
        if len(word) < 3:
            # 2 字母词靠白名单，不靠形态判断
            assert _looks_like_title_word(word) is False
        else:
            assert _looks_like_title_word(word) is True

    @pytest.mark.parametrize("word", ["FRDS", "CMCT", "NTb", "PlayWEB", "HDSWEB", "x265", "U2"])
    def test_release_group_shape(self, word):
        assert _looks_like_title_word(word) is False


class TestWordListCoversCommonShortWords:
    @pytest.mark.parametrize(
        "word",
        ["us", "man", "men", "her", "him", "she", "who", "why", "new", "old"],
    )
    def test_short_title_words_listed(self, word):
        """2 字母词全靠白名单保护，缺失就会被当后缀剥掉。"""
        assert word in _HIGH_FREQ_TITLE_WORDS

    def test_technical_tags_not_listed(self):
        """技术标签不能被当成片名保护，否则会残留在搜索词里。"""
        for tag in ("hd", "sd", "ts", "v2", "v3", "dd"):
            assert tag not in _HIGH_FREQ_TITLE_WORDS
