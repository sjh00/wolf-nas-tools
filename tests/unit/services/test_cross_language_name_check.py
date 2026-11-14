"""跨语言名称交叉校验：同一部剧不能被识别成两个作品。

真实故障：同一批文件（英文名都是 The Great Long March）被 LLM 识别出多种
中文名 —— 伟大的长征 / 伟大长征 / 天下长征 / 万里长征 / 长征。
其中「长征」按中文名搜索命中了另一部同名老剧《长征》(2001, TMDB 100669)，
而正确的《伟大的长征》(2026, TMDB 297253) 才是源文件对应的作品。
同一部剧因此在媒体库里分裂成两个条目。

修复：中文名可能来自 LLM（有幻觉），英文名来自文件名（稳定）。
按中文名搜到的结果必须通过英文名交叉校验，不通过就改走英文名搜索。
"""

import pytest

from app.media.lookup.tmdb_client import (
    STRICT_NAME_RATIO,
    compare_tmdb_names,
    compare_tmdb_names_strict,
)

# TMDB 100669《长征》(2001) 的名称集合
LONG_MARCH_2001 = ["长征", "The Long March", "Long March"]
# TMDB 297253《伟大的长征》(2026) 的名称集合
GREAT_LONG_MARCH_2026 = ["伟大的长征", "The Great Long March"]


class TestWrongWorkIsRejected:
    def test_loose_compare_would_misfire(self):
        """说明为什么必须加严格版：宽松比对会把两部剧当成同一部。"""
        assert compare_tmdb_names("The Great Long March", LONG_MARCH_2001) is True

    def test_strict_compare_rejects_other_work(self):
        assert compare_tmdb_names_strict("The Great Long March", LONG_MARCH_2001) is False

    def test_strict_compare_accepts_correct_work(self):
        assert compare_tmdb_names_strict("The Great Long March", GREAT_LONG_MARCH_2026) is True

    def test_exact_match_accepted(self):
        assert compare_tmdb_names_strict("The Long March", LONG_MARCH_2001) is True

    def test_chinese_name_still_matches_chinese(self):
        """同名中文作品本身仍应匹配（严格版不是禁掉中文）。"""
        assert compare_tmdb_names_strict("长征", LONG_MARCH_2001) is True


class TestAmbiguousChineseNames:
    @pytest.mark.parametrize(
        "cn",
        ["伟大的长征", "伟大长征", "天下长征", "万里长征"],
    )
    def test_hallucinated_names_miss_the_old_show(self, cn):
        """除「长征」外的幻觉名不会命中老剧，说明只有个别幻觉会造成分裂。"""
        assert compare_tmdb_names(cn, LONG_MARCH_2001) is False

    def test_bare_short_name_hits_old_show(self):
        """只有截断成「长征」才会命中老剧 —— 这正是分裂的入口。"""
        assert compare_tmdb_names("长征", LONG_MARCH_2001) is True


class TestStrictRatioGuard:
    def test_threshold_is_stricter_than_loose(self):
        assert STRICT_NAME_RATIO > 0.75

    def test_empty_inputs_rejected(self):
        assert compare_tmdb_names_strict("", ["x"]) is False
        assert compare_tmdb_names_strict("abc", []) is False

    def test_short_names_skipped(self):
        assert compare_tmdb_names_strict("ab", ["ab"]) is False
