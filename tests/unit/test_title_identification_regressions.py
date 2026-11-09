"""作品名识别缺陷回归。

三条独立缺陷，均可在构造样例上复现：

1. 广告清洗误伤：`Movie.2010.CC.BluRay` / `Show.2019.TV.1080p` 里的
   `<年份>.CC` / `<年份>.TV` 被当成「数字域名广告」整段删除，年份与标题被削。
   典型样例：`Show.Name.1997.CC.BDRip.1080p` → 年份丢失（year=None）
   → TMDB 错配到另一部同年份作品。

2. 片名自带年份被当出品年：`Reply.1988.S01E16.2015...` 这类命名
   → 标题只剩 `Reply`、年份记成 1988 → 同一部剧被拆成多个 TMDB 条目。

3. 裁词重试削掉实词：多词片名整名搜不到时裁掉尾词 → 恰好命中另一部
   同名作品 → 片名被削且认错片。
"""

import pytest

from app.domain.media_types import ProviderMediaType
from app.domain.validators.media_title import clean_advertisement_title, is_advertisement_title
from app.media.lookup.tmdb_lookup import TmdbLookup
from app.media.parser import RegexParser
from app.media.parser.base import ParserResult

# ---------- 1. 广告清洗不得误伤年份 + 场景标签 ----------

@pytest.mark.parametrize(
    "name",
    [
        "Show.Name.1997.CC.BDRip.1080p.x265.10bit.DDP5.1.2Audio-GROUP.mkv",
        "Show.Name.2019.TV.1080p.WEB-DL.mkv",
        "Movie.2010.CC.BluRay.mkv",
        "Channel.2021.ME.mkv",
        "Film.2015.IO.1080p.mkv",
        "片名.2018.TOP.WEB-DL.mkv",
    ],
)
def test_year_with_scene_tag_is_not_advertisement(name):
    """`年份 + .CC/.TV/.ME/.IO/.TOP` 是场景分隔符，不是广告域名。"""
    assert is_advertisement_title(name) is False
    assert clean_advertisement_title(name) == name

def test_real_numeric_domain_is_still_removed():
    """真正的数字域名广告仍要被剥掉（含站名粘连与全角冒号）。"""
    assert is_advertisement_title("某片网：4488569.com") is True
    cleaned = clean_advertisement_title("某片网：4488569.com" + " 电影名") or ""
    assert "4488569" not in cleaned
    assert "电影名" in cleaned

def test_year_at_token_end_with_tld_still_ok():
    """域名规则只认「终结」的 TLD，年份后跟技术标签时不受影响。"""
    assert is_advertisement_title("Movie.1999.CC.BluRay.1080p.mkv") is False

# ---------- 2. 片名自带年份 ----------

def test_title_year_kept_when_episode_marker_follows():
    """《请回答1988》：1988 属于片名，出品年是季集号之后的 2015。"""
    parsed = RegexParser().parse("Reply.1988.S01E16.2015.1080p.Netflix.WEB-DL.AVC.AAC.2.0-DBTV.mkv")
    assert parsed is not None
    assert parsed.year == "2015"
    assert parsed.title_en == "Reply 1988"
    assert parsed.season == 1
    assert parsed.episode == 16

def test_year_in_title_without_episode_marker():
    """无季集号时保持原有行为：取最后一个年份（Wonder Woman 1984 2020）。"""
    parsed = RegexParser().parse("Wonder.Woman.1984.2020.1080p.BluRay.x264.mkv")
    assert parsed is not None
    assert parsed.year == "2020"

def test_release_year_after_episode_marker_preferred():
    """季集号之后的年份优先于片名中的年份。"""
    parsed = RegexParser().parse("The.100.2014.S01E01.2014.1080p.WEB-DL.mkv")
    assert parsed is not None
    assert parsed.year == "2014"

def test_year_after_scene_tag_restored():
    """`1997.CC` 不再被广告规则删掉，年份可正常识别。"""
    parsed = RegexParser().parse(
        "Show.Name.Part.Two.and.Three.1997.CC.BDRip.1080p.x265.10bit.DDP5.1.2Audio-GROUP.mkv"
    )
    assert parsed is not None
    assert parsed.year == "1997"
    assert parsed.title_en == "Show Name Part Two And Three"

# ---------- 3. 裁词重试只能裁标签 ----------

class TestTrimmableTag:
    @pytest.mark.parametrize("token", ["Ma", "TX", "1080p", "WEB", "HFR", "x265", "2024", "A", "AD", "2AUDIO"])
    def test_tag_like_tokens_are_trimmable(self, token):
        assert TmdbLookup._is_trimmable_tag(token) is True

    @pytest.mark.parametrize("token", ["Cop", "Returns", "Rises", "Begins", "Story", "Affairs", "Hollywood"])
    def test_title_words_are_not_trimmable(self, token):
        assert TmdbLookup._is_trimmable_tag(token) is False

    def test_trim_does_not_shrink_meaningful_title(self):
        """多词片名（如 `Sample Title Cop`）不得被裁成 `Sample Title`。"""
        parsed = ParserResult(title_en="Sample Title Cop", year="1996", type=ProviderMediaType.MOVIE)
        lookup = TmdbLookup(client=__import__("unittest.mock", fromlist=["MagicMock"]).MagicMock())
        searched: list[str] = []

        def fake_search(name, year=None):
            searched.append(name)
            return {
                "id": 1,
                "title": "Sample Title",
                "release_date": "1996-01-01",
                "genre_ids": [18],
            }

        lookup.search.search_movie = fake_search  # type: ignore[method-assign]
        assert lookup._lookup_trimmed_tail(parsed, ProviderMediaType.MOVIE, None) == {}
        assert searched == [], "实词不应触发裁剪搜索"
