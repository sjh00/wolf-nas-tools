"""季号等价写法工具：跨层（媒体信息 / 转移事件 / 数据库）比较的唯一口径。"""

import pytest

from app.utils.string_utils import season_matches, season_variants


@pytest.mark.parametrize(
    ("season", "expected_member"),
    [
        ("1", "S01"),
        ("S1", "S01"),
        ("S01", "S01"),
        ("01", "S01"),
        (1, "S01"),
        (2, "S02"),
        ("S13", "S13"),
        (13, "S13"),
    ],
)
def test_variants_cover_common_spellings(season, expected_member):
    assert expected_member in season_variants(season)


def test_variants_empty():
    assert season_variants(None) == []
    assert season_variants("") == []


def test_variants_non_numeric_kept_verbatim():
    assert season_variants("特别篇") == ["特别篇"]


@pytest.mark.parametrize(
    ("left", "right"),
    [("1", "S01"), ("S1", "1"), (2, "S02"), ("S13", 13), ("S02", "S02")],
)
def test_matches_true(left, right):
    assert season_matches(left, right) is True


@pytest.mark.parametrize(("left", "right"), [("1", "S02"), ("S02", "3"), (2, 3)])
def test_matches_false(left, right):
    assert season_matches(left, right) is False


def test_matches_empty_left_is_not_constraining():
    """左侧无季号时不构成约束（调用方据此决定是否加过滤条件）。"""
    assert season_matches(None, "S01") is True
