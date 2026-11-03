"""提取规则基类与编排器"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Pattern

from ..types import ExtractedElement, ParseContext


@dataclass
class ExtractionRule:
    """元数据提取规则"""

    name: str
    pattern: Pattern[str]
    category: str
    priority: int = 50
    consumes: bool = True
    confidence: float = 0.9
    stop: bool = False
    _extract_fn: Callable[[re.Match[str], str], dict[str, Any] | None] | None = field(default=None, repr=False)

    def extract(self, match: re.Match[str], text: str) -> dict[str, Any] | None:
        if self._extract_fn:
            return self._extract_fn(match, text)
        groups = match.groups()
        if len(groups) == 1:
            return {self.category: int(groups[0]) if groups[0].isdigit() else groups[0]}
        return {self.category: match.group(0)}


@dataclass
class RuleEngine:
    """规则引擎：按优先级顺序应用规则，管理文本消费"""

    rules: list[ExtractionRule] = field(default_factory=list)

    def add_rule(self, rule: ExtractionRule) -> None:
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)

    def extract_all(self, text: str) -> list[ExtractedElement]:
        elements: list[ExtractedElement] = []
        consumed: list[tuple[int, int]] = []
        category_stop: set[str] = set()
        for rule in self.rules:
            if rule.category in category_stop:
                continue
            match = rule.pattern.search(text)
            if not match:
                continue
            start, end = match.span()
            if any(start < c_end and end > c_start for c_start, c_end in consumed):
                continue
            extracted = rule.extract(match, text)
            if not extracted:
                continue
            for key, value in extracted.items():
                elem = ExtractedElement(
                    category=key,
                    value=value,
                    confidence=rule.confidence,
                    rule_name=rule.name,
                    span=(start, end),
                    consumed=rule.consumes,
                )
                elements.append(elem)
            if rule.consumes:
                consumed.append((start, end))
            if rule.stop:
                category_stop.add(rule.category)
        return elements

    def apply(self, ctx: ParseContext) -> ParseContext:
        elements = self.extract_all(ctx.text)
        self._refine_year(ctx, elements)
        for elem in elements:
            ctx.add_element(elem)
            if elem.category == "episode":
                ctx.episode = elem.value
            elif elem.category == "season":
                ctx.season = elem.value
            elif elem.category == "year":
                ctx.year = str(elem.value)
            elif elem.category == "resolution":
                ctx.resolution = elem.value
            elif elem.category == "source":
                ctx.source = elem.value
            elif elem.category == "video_codec":
                ctx.video_codec = elem.value
            elif elem.category == "audio_codec":
                ctx.audio_codec = elem.value
            elif elem.category == "resource_team":
                ctx.resource_team = elem.value
            elif elem.category == "episode_title":
                ctx.episode_title = elem.value
            elif elem.category == "release_group":
                ctx.release_group = elem.value
        return ctx

    @staticmethod
    def _refine_year(ctx: ParseContext, elements: list[ExtractedElement]) -> None:
        """季集号存在时，把「季集号之后的年份」定为出品年，片名里的年份还给标题。

        真实故障：`Reply.1988.S01E16.2015.1080p...`（韩剧《请回答1988》）
        年份规则先吃掉了紧贴片名的 1988 → 标题只剩 `Reply`、出品年记成 1988，
        TMDB 于是匹配到另一部同名影片（线上数据里同一条剧被记成 2022 / 2026 两个
        不同 TMDB 的电影）。

        命名惯例里出品年紧跟在片名后，但片名自身含年份时（Reply 1988、
        Wonder Woman 1984）会出现「片名年份 … 季集号 … 出品年」的顺序，
        此时季集号之后的那个年份才是出品年。被替换掉的年份不消费，
        让它回到标题里，标题才能还原成 `Reply 1988`。
        """
        year_elems = [e for e in elements if e.category == "year"]
        if not year_elems:
            return
        sxx_spans = [e.span for e in elements if e.rule_name.startswith("sxxexx")]
        if not sxx_spans:
            return
        boundary = max(end for _, end in sxx_spans)
        # 年份规则带 stop，只会留下一个候选；季集号之后的出品年需要单独扫出来
        later = re.search(r"\b(19\d{2}|20[0-3]\d)\b", ctx.text[boundary:])
        if not later:
            return
        start = boundary + later.start(1)
        end = boundary + later.end(1)
        for elem in list(year_elems):
            if elem.span[0] >= boundary:
                # 已经选中的就是出品年
                return
            # 片名里的年份：不消费、不记为元数据，让它回到标题
            elements.remove(elem)
        elements.append(
            ExtractedElement(
                category="year",
                value=int(later.group(1)),
                confidence=0.85,
                rule_name="year_after_episode",
                span=(start, end),
                consumed=True,
            )
        )


def get_rule_engine() -> RuleEngine:
    from . import (  # noqa: PLC0415  # 规则模块循环引用，延迟导入解除
        codec_rules,
        episode_rules,
        resolution_rules,
        season_rules,
        source_rules,
        year_rules,
    )

    engine = RuleEngine()
    for rule in season_rules.RULES:
        engine.add_rule(rule)
    for rule in episode_rules.RULES:
        engine.add_rule(rule)
    for rule in year_rules.RULES:
        engine.add_rule(rule)
    for rule in resolution_rules.RULES:
        engine.add_rule(rule)
    for rule in codec_rules.RULES:
        engine.add_rule(rule)
    for rule in source_rules.RULES:
        engine.add_rule(rule)
    return engine
