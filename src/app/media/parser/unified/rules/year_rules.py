"""年份提取规则 — 含多候选消歧"""

from __future__ import annotations

import re

from .base import ExtractionRule

_R_YEAR = r"19\d{2}|20[0-2]\d|2030"
# 负向前瞻：年份后面（空格/点/连字符/下划线后）不应再跟年份，
# 使裸年份规则取"最后一个年份"——"Wonder Woman 1984 2020" 应取 2020、1984 保留片名
_R_NOT_FOLLOWED_BY_YEAR = rf"(?![\s._\-]*(?:{_R_YEAR}))"

RULES: list[ExtractionRule] = [
    ExtractionRule(
        name="bracket_year",
        pattern=re.compile(rf"\[({_R_YEAR})\]"),
        category="year",
        priority=90,
        confidence=0.9,
        stop=True,
    ),
    ExtractionRule(
        name="paren_year",
        pattern=re.compile(rf"\(({_R_YEAR})\)"),
        category="year",
        priority=85,
        confidence=0.9,
        stop=True,
    ),
    ExtractionRule(
        name="bare_year_after_title",
        pattern=re.compile(r"(?<=[a-zA-Z)%])[.\s]+(" + _R_YEAR + r")\b" + _R_NOT_FOLLOWED_BY_YEAR),
        category="year",
        priority=60,
        confidence=0.8,
        stop=True,
    ),
    ExtractionRule(
        name="bare_year",
        pattern=re.compile(r"\b(" + _R_YEAR + r")\b" + _R_NOT_FOLLOWED_BY_YEAR),
        category="year",
        priority=55,
        confidence=0.7,
        stop=True,
    ),
]
