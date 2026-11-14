"""MediaRecognizer → BaseParser 适配器

agent 层实现 media 层定义的 BaseParser 端口（依赖倒置）：
media 层不再 import agent 层，由 Builder 注入本适配器。
"""

from app.agent.agents.media_recognizer import MediaRecognizer, MediaResult
from app.domain.media_types import ProviderMediaType
from app.media.parser.base import BaseParser, ParserResult


class MediaRecognizerParser(BaseParser):
    """基于 LLM 的解析器 — 包装 MediaRecognizer 并实现 BaseParser 端口"""

    is_llm: bool = True

    def __init__(self, recognizer: MediaRecognizer):
        self._recognizer = recognizer

    @property
    def ready(self) -> bool:
        return self._recognizer.ready

    def parse(self, title: str, subtitle: str = "") -> ParserResult | None:
        result = self._recognizer.recognize(title)
        if not result:
            return None
        return self._convert(result, title)

    def parse_batch(self, titles: list[str]) -> list[ParserResult | None]:
        results = self._recognizer.recognize_batch(titles)
        return [self._convert(r, t) for r, t in zip(results, titles, strict=False)]

    def _convert(self, result: MediaResult | None, org_title: str = "") -> ParserResult | None:
        if not result:
            return None
        return ParserResult(
            title_en=result.title_en,
            title_cn=result.title_cn,
            year=str(result.year) if result.year else None,
            season=result.season,
            end_season=result.end_season,
            episode=result.episode,
            end_episode=result.end_episode,
            resource_pix=result.resolution,
            video_encode=result.video_codec,
            audio_encode=result.audio_codec,
            resource_team=result.release_group,
            type=self._map_type(result.type),
            # 用模型自评的置信度；未给或越界时退回保守值 0.5，
            # 这样「模型没说有把握」不会被当成高可信结果采纳。
            confidence=self._resolve_confidence(result.confidence),
            org_string=org_title or None,
        )

    @staticmethod
    def _resolve_confidence(value: float | None) -> float:
        if value is None:
            return 0.5
        try:
            conf = float(value)
        except (TypeError, ValueError):
            return 0.5
        # 容忍 0-100 的百分比写法
        if 1.0 < conf <= 100.0:
            conf = conf / 100.0
        if conf < 0.0 or conf > 1.0:
            return 0.5
        return round(conf, 2)

    @staticmethod
    def _map_type(type_str: str | None) -> ProviderMediaType | None:
        if type_str == "anime":
            return ProviderMediaType.ANIME
        if type_str == "tv":
            return ProviderMediaType.SERIES
        if type_str == "movie":
            return ProviderMediaType.MOVIE
        return None
