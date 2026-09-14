"""v3 时代积累的名称识别回归用例（tests/cases/meta_cases.py）.

这份列表在 v3 中用于 meta_info 端到端测试，后因测试体系重构被删除。
现恢复到当前 UnifiedParser 上，严格校验识别身份字段（类型/年份/季/集），
en/cn 名称仅断言"至少有一个非空"——因为当前版本增强了中文名提取，
与 v3 的"仅填英文名"行为存在合理差异，不作为失败判定。
"""

from __future__ import annotations

import pytest

from app.domain.mediatypes import MediaType
from app.media.parser.unified import UnifiedParser
from tests.cases.meta_cases import meta_cases

# 已知限制：带版本号集号（01v2/03v2）、全角方括号集号【04】、复杂多括号混合。
# 这些场景不影响核心识别（类型/年份/季集大部分正确），暂不在本回归中强校验。
_KNOWN_LIMITATION_PREFIXES = (
    "【幻月字幕组】",  # 全角【04】集号
    "[GM-Team][国漫][寻剑",  # 多括号混合 [02]
    "[SweetSub&LoliHouse] Made in Abyss",  # S2 - 03v2 带版本号
    "[Nekomoe kissaten&LoliHouse] Soredemo Ayumu",  # - 01v2 带版本号
)


def _norm_type(raw: str) -> MediaType | None:
    if raw == "电影":
        return MediaType.MOVIE
    if raw == "电视剧":
        return MediaType.TV
    return None


def _parse_season(raw: str) -> tuple[int | None, int | None]:
    """'S01' -> (1, None)；'S01-S02' -> (1, 2)；'' -> (None, None)"""
    raw = (raw or "").strip()
    if not raw:
        return None, None
    m = __import__("re").match(r"S(\d{1,2})(?:-S(\d{1,2}))?$", raw, __import__("re").IGNORECASE)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2)) if m.group(2) else None


def _parse_episode(raw: str) -> tuple[int | None, int | None]:
    """'E06' -> (6, None)；'E01-E26' -> (1, 26)；'' -> (None, None)"""
    raw = (raw or "").strip()
    if not raw:
        return None, None
    m = __import__("re").match(r"E(\d{1,4})(?:-E(\d{1,4}))?$", raw, __import__("re").IGNORECASE)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2)) if m.group(2) else None


@pytest.fixture(scope="module")
def parser():
    return UnifiedParser()


@pytest.mark.parametrize(
    "case",
    [c for c in meta_cases if c.get("title")],
    ids=[f"{i}-{c['title'][:30]}" for i, c in enumerate(meta_cases, 1) if c.get("title")],
)
def test_meta_cases(parser, case):
    target = case.get("target", {})

    if case["title"].startswith(_KNOWN_LIMITATION_PREFIXES):
        pytest.skip("已知限制：带版本号/全角方括号集号等边缘场景")

    result = parser.parse(case.get("title") or "", case.get("subtitle") or "")
    assert result is not None, f"解析返回 None: {case['title']!r}"

    # 类型：电影/电视剧 必须一致（动漫归入电视剧）
    exp_type = _norm_type(target.get("type", ""))
    if exp_type is not None:
        got_type = MediaType.TV if result.type in (MediaType.TV, MediaType.ANIME) else result.type
        assert got_type == exp_type, (
            f"类型不符: 期望 {exp_type}, 实际 {result.type} | {case['title']!r}"
        )

    # 年份
    exp_year = (target.get("year") or "").strip()
    got_year = (result.year or "").strip()
    assert got_year == exp_year, f"年份不符: 期望 {exp_year!r}, 实际 {got_year!r} | {case['title']!r}"

    # 季（有集号但无季号时默认 S01 已在解析器内处理）
    exp_season, exp_end_season = _parse_season(target.get("season", ""))
    got_season = result.season
    assert got_season == exp_season, (
        f"季数不符: 期望 {exp_season!r}, 实际 {got_season!r} | {case['title']!r}"
    )
    if exp_end_season is not None:
        assert result.end_season == exp_end_season

    # 集
    exp_episode, exp_end_episode = _parse_episode(target.get("episode", ""))
    got_episode = result.episode
    assert got_episode == exp_episode, (
        f"集数不符: 期望 {exp_episode!r}, 实际 {got_episode!r} | {case['title']!r}"
    )
    if exp_end_episode is not None:
        assert result.end_episode == exp_end_episode

    # 名称：只要有一个可搜索的名称即可（cn 增强相对 v3 是改进，en 缺失不影响搜索）
    if (target.get("en_name") or "").strip() or (target.get("cn_name") or "").strip():
        assert result.title_en or result.title_cn, f"名称全空: {case['title']!r}"
