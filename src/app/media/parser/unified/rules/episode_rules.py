"""集数提取规则"""

from __future__ import annotations

import re

import cn2an

from .base import ExtractionRule


def _is_year_token(value: int) -> bool:
    return 1900 <= value <= 2030


def _dash_ep_range_extract(match: re.Match[str], _: str) -> dict[str, list[int]] | None:
    begin, end = int(match.group(1)), int(match.group(2))
    # 2007-2009 / 1996-2018 是合集年份区间，不是集数
    if _is_year_token(begin) and _is_year_token(end) and end >= begin:
        return None
    return {"episode": [begin, end]}


def _cn2an_extract(match: re.Match[str]) -> dict[str, int] | None:
    try:
        val = int(cn2an.cn2an(match.group(1), mode="smart"))
        return {"episode": val}
    except Exception:
        return None


def _compact_air_date_extract(match: re.Match[str]) -> dict[str, int] | None:
    """YYYYMMDD 紧凑播出日期 → 集号。

    电视栏目常按播出日期命名（`节目名.20061023.本期标题`），没有 SxxExx。
    这类文件若拿不到集号，会整批落到「未识别」。用月日（MMDD）作集号：
    同一年内唯一、可排序，且能从命名反推播出日期。
    日期本身还要校验月份/日合法，避免把 8 位哈希误认成日期。
    """
    text = match.group(0)
    month, day = int(text[4:6]), int(text[6:8])
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return {"season": 1, "episode": month * 100 + day}


RULES: list[ExtractionRule] = [
    ExtractionRule(
        name="compact_air_date",
        # 节目名.20061023.本期标题：优先级低于所有 SxxExx/EPxx，
        # 仅在没有任何常规集号时兜底
        pattern=re.compile(r"\b((?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))\b"),
        category="episode",
        priority=55,
        confidence=0.8,
        stop=True,
        _extract_fn=lambda m, _: _compact_air_date_extract(m),
    ),
    ExtractionRule(
        name="sxxexx_resolution_tight",
        # 集号与分辨率粘连（S01E071080p = S01E07 + 1080p）：非贪婪集号 + 前瞻分辨率截断，
        # 避免 \d+ 贪婪把 07+1080 全当集号
        pattern=re.compile(r"[Ss](\d+)[Ee](\d+?)(?=(?:2160|1080|720|480|576)[pPiI]\b)", re.IGNORECASE),
        category="episode",
        priority=101,
        confidence=0.95,
        stop=True,
        _extract_fn=lambda m, _: {
            "season": int(m.group(1)),
            "episode": int(m.group(2)),
        },
    ),
    ExtractionRule(
        name="sxxexx_range",
        pattern=re.compile(r"[Ss](\d+)[Ee](\d+)[-~][Ee](\d+)", re.IGNORECASE),
        category="episode",
        priority=102,
        confidence=0.95,
        stop=True,
        _extract_fn=lambda m, _: {
            "season": int(m.group(1)),
            "episode": [int(m.group(2)), int(m.group(3))],
        },
    ),
    ExtractionRule(
        name="sxxexx",
        pattern=re.compile(r"[Ss](\d+)[Ee](\d+)", re.IGNORECASE),
        category="episode",
        priority=100,
        confidence=0.95,
        stop=True,
        _extract_fn=lambda m, _: {
            "season": int(m.group(1)),
            "episode": int(m.group(2)),
        },
    ),
    ExtractionRule(
        name="season_ep_keyword",
        pattern=re.compile(r"Season\s*(\d+)\s*Episode\s*(\d+)", re.IGNORECASE),
        category="episode",
        priority=95,
        confidence=0.95,
        stop=True,
        _extract_fn=lambda m, _: {
            "season": int(m.group(1)),
            "episode": int(m.group(2)),
        },
    ),
    ExtractionRule(
        name="bracket_range",
        pattern=re.compile(r"\[(\d{1,4})[-~](\d{1,4})\]"),
        category="episode",
        priority=90,
        confidence=0.9,
        stop=True,
        _extract_fn=lambda m, _: {"episode": [int(m.group(1)), int(m.group(2))]},
    ),
    ExtractionRule(
        name="e_dash_e_range",
        pattern=re.compile(r"\b[Ee](\d{1,4})[-~][Ee](\d{1,4})\b"),
        category="episode",
        priority=88,
        confidence=0.85,
        stop=True,
        _extract_fn=lambda m, _: {"episode": [int(m.group(1)), int(m.group(2))]},
    ),
    ExtractionRule(
        name="ep_to_ep_range",
        # EP001-EP131 / EP01-08 / EP001-EP131ed（ed=edited 合集后缀）
        pattern=re.compile(r"\bEP?(\d{1,4})[-~]EP?(\d{1,4})(?:ed)?\b", re.IGNORECASE),
        category="episode",
        priority=89,
        confidence=0.9,
        stop=True,
        _extract_fn=lambda m, _: {"episode": [int(m.group(1)), int(m.group(2))]},
    ),
    ExtractionRule(
        name="ep_dash_num_range",
        pattern=re.compile(r"\bEP?(\d{1,4})[-~](\d{1,4})\b", re.IGNORECASE),
        category="episode",
        priority=87,
        confidence=0.85,
        stop=True,
        _extract_fn=lambda m, _: {"episode": [int(m.group(1)), int(m.group(2))]},
    ),
    ExtractionRule(
        name="dash_ep_range",
        pattern=re.compile(r"\b(\d{1,4})[-~](\d{1,4})\b(?![pP])"),
        category="episode",
        priority=85,
        confidence=0.85,
        stop=True,
        _extract_fn=_dash_ep_range_extract,
    ),
    ExtractionRule(
        name="bracket_ep",
        # 支持 [14]、[14v2]，以及 [14+sp14]/[06+sp06]（正片集号 + 同号特别篇，取正片集号）
        pattern=re.compile(r"\[(\d{1,4})(?:[vV]\d+)?(?:\s*\+\s*[sS][pP]\d*)?\]"),
        category="episode",
        priority=80,
        confidence=0.9,
        stop=True,
    ),
    ExtractionRule(
        name="ep_plus_special",
        # 裸集号 + 特别篇：14+sp14 / 06+SP06 → 取正片集号
        pattern=re.compile(r"\b(\d{1,4})\s*\+\s*[sS][pP]\d*\b"),
        category="episode",
        priority=78,
        confidence=0.85,
        stop=True,
    ),
    ExtractionRule(
        name="ep_prefix",
        pattern=re.compile(r"\bEP?(\d{1,4})\b", re.IGNORECASE),
        category="episode",
        priority=75,
        confidence=0.85,
        stop=True,
    ),
    ExtractionRule(
        name="chinese_ep_range",
        pattern=re.compile(r"第\s*(\d+)\s*[-~]\s*(\d+)\s*[集话話期]"),
        category="episode",
        priority=72,
        confidence=0.85,
        stop=True,
        _extract_fn=lambda m, _: {"episode": [int(m.group(1)), int(m.group(2))]},
    ),
    ExtractionRule(
        name="chinese_ep",
        pattern=re.compile(r"第\s*(\d+)\s*[集话話期]"),
        category="episode",
        priority=70,
        confidence=0.85,
        stop=True,
    ),
    ExtractionRule(
        name="chinese_number_ep",
        pattern=re.compile(r"第([一二三四五六七八九十百]+)集"),
        category="episode",
        priority=65,
        confidence=0.85,
        stop=True,
        _extract_fn=lambda m, _: _cn2an_extract(m),
    ),
    ExtractionRule(
        name="dash_ep",
        pattern=re.compile(r"\s[-~]\s*(\d{1,4})\b"),
        category="episode",
        priority=60,
        confidence=0.75,
        stop=True,
    ),
    ExtractionRule(
        name="pipe_ep",
        pattern=re.compile(r"\|(\d{1,4})\b"),
        category="episode",
        priority=58,
        confidence=0.7,
        stop=True,
    ),
    ExtractionRule(
        name="trailing_ep",
        pattern=re.compile(r"(\d{1,4})\s+[繁简]"),
        category="episode",
        priority=56,
        confidence=0.65,
        stop=True,
    ),
    ExtractionRule(
        name="hash_ep",
        pattern=re.compile(r"#(\d{1,4})\b"),
        category="episode",
        priority=55,
        confidence=0.7,
        stop=True,
    ),
    ExtractionRule(
        name="bare_episode",
        # 数字后紧跟连字符+字母（100-nin）或普通单词（The 100 Girlfriends）属于标题词，不是集号；
        # 裸集号后面应紧跟技术信息起点（括号/点/连字符/数字）或标题结尾。
        # 限制 1-2 位：3 位数字（如 The 355）几乎不会是裸集号，避免电影标题数字被误判
        # 不能位于文件名开头：片名本身就可能以数字开头（`2.Insurgent.2015` 是
        # 《分歧者2》、`20.Once.Again.2015` 是《重返20岁》），开头的数字后面接
        # 英文单词时是片名的一部分。裸集号总在剧名之后，前面必然还有内容。
        pattern=re.compile(
            r"(?!^)(?<![.\d\-×xX/])\b(0?[1-9]\d?)\b(?!\s*[pP]\b)(?!\.\d)(?![-~][a-zA-Z])(?=\s*(?:[\[\]()._\-]|\d|$))"
        ),
        category="episode",
        priority=50,
        confidence=0.5,
        stop=True,
    ),
]
