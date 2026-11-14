"""解析置信度门槛：低置信度结果不得被当成有效识别.

规则只切出零碎词、或模型自评没把握时，解析结果不能直接入库——
宁可交给 LLM 兜底，兜底也达不到阈值就标未识别。
"""

import pytest

from app.agent.agents.recognizer_adapter import MediaRecognizerParser
from app.core.settings import settings
from app.media.parser.base import ParserResult
from app.media.service import MediaService


@pytest.fixture
def svc(monkeypatch):
    """构造只测判定逻辑的 MediaService（绕开完整 DI），阈值固定 0.75。"""
    monkeypatch.setattr(MediaService, "_parse_confidence_min", lambda self: 0.75)
    return MediaService.__new__(MediaService)


class TestConfidenceGate:
    def test_high_confidence_accepted(self, svc):
        parsed = ParserResult(title_en="Some Movie", year="2024", confidence=0.95)
        assert svc._is_reliable_parse(parsed) is True

    def test_low_confidence_rejected(self, svc):
        parsed = ParserResult(title_en="Some Movie", year="2024", confidence=0.4)
        assert svc._is_reliable_parse(parsed) is False

    def test_boundary_equals_threshold_accepted(self, svc):
        parsed = ParserResult(title_en="Some Movie", confidence=0.75)
        assert svc._is_reliable_parse(parsed) is True

    def test_missing_confidence_rejected(self, svc):
        """未给出置信度视为不可信，不能默认放行。"""
        parsed = ParserResult(title_en="Some Movie", confidence=0.0)
        assert svc._is_reliable_parse(parsed) is False

    def test_title_noise_still_rejected_even_if_confident(self, svc):
        parsed = ParserResult(title_en="Some Movie 1080p BluRay", confidence=0.99)
        assert svc._is_reliable_parse(parsed) is False

    def test_empty_title_rejected(self, svc):
        parsed = ParserResult(title_en="", confidence=0.99)
        assert svc._is_reliable_parse(parsed) is False


class TestThresholdConfig:
    def test_default_is_strict(self):
        media = settings.get("media")
        assert "parse_confidence_min" in media
        assert 0.0 < media["parse_confidence_min"] <= 1.0


class TestLlmConfidenceResolution:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (0.92, 0.92),
            (92, 0.92),          # 百分比写法
            (0.0, 0.0),
            (1.0, 1.0),
            (None, 0.5),         # 模型没给 → 保守值
            (150, 0.5),          # 越界 → 保守值
            (-1, 0.5),
            ("abc", 0.5),
        ],
    )
    def test_resolve(self, raw, expected):
        assert MediaRecognizerParser._resolve_confidence(raw) == expected
