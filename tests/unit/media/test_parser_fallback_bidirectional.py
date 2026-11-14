"""解析回落必须是双向的：LLM 不可用时回落到本地规则解析器。

真实故障：LLM 额度耗尽（429）后 `MediaInfo.type` 为空、整批文件被判为「未识别」。
本地规则解析器（RegexParser / UnifiedParser）一直可用，但编排只做了
「规则失败 → LLM 兜底」单向回落，LLM 一旦启用就再也没有回落路径。
"""

from unittest.mock import MagicMock

import pytest

from app.domain.media_types import ProviderMediaType
from app.media.parser.base import BaseParser, ParserResult
from app.media.service import MediaService


class _FakeParser(BaseParser):
    """可控的假解析器：记录调用次数，按配置返回结果或失败。"""

    def __init__(self, *, is_llm: bool, result: ParserResult | None, ready: bool = True):
        self.is_llm = is_llm
        self._result = result
        self._ready = ready
        self.calls: list[tuple[str, str]] = []

    @property
    def ready(self) -> bool:
        return self._ready

    def parse(self, title: str, subtitle: str = "") -> ParserResult | None:
        self.calls.append((title, subtitle))
        return self._result

    def parse_batch(self, titles: list[str]) -> list[ParserResult | None]:
        return [self.parse(t) for t in titles]

def _service(llm_parser: BaseParser, regex_parser: BaseParser) -> MediaService:
    svc = MediaService.__new__(MediaService)
    svc._llm_parser = llm_parser
    svc._regex_parser = regex_parser
    svc._parser = llm_parser
    svc._lookup = MagicMock()
    svc._episode_mapper = MagicMock()
    svc._episode_remapper = MagicMock()
    svc._search_keyword = None
    svc._search_tmdbweb = None
    svc._default_language = "zh"
    svc._episode_mapping_enabled = False
    svc._rmt_match_mode = MagicMock()
    return svc

_OK_RULE = ParserResult(title_cn="测试影片", year="2024", type=ProviderMediaType.MOVIE)

class TestFallbackParserSelection:
    def test_llm_primary_falls_back_to_regex(self):
        llm = _FakeParser(is_llm=True, result=None)
        regex = _FakeParser(is_llm=False, result=_OK_RULE)
        svc = _service(llm, regex)

        assert svc._fallback_parser() is regex
        assert svc._fallback_label() == "本地规则"

    def test_regex_primary_falls_back_to_llm_when_ready(self):
        llm = _FakeParser(is_llm=True, result=_OK_RULE, ready=True)
        regex = _FakeParser(is_llm=False, result=None)
        svc = _service(llm, regex)
        svc._parser = regex

        assert svc._fallback_parser() is llm
        assert svc._fallback_label() == "LLM"

    def test_regex_primary_has_no_fallback_when_llm_not_ready(self):
        llm = _FakeParser(is_llm=True, result=_OK_RULE, ready=False)
        regex = _FakeParser(is_llm=False, result=None)
        svc = _service(llm, regex)
        svc._parser = regex

        assert svc._fallback_parser() is None

    def test_unavailable_primary_is_replaced_by_rule(self):
        """LLM 冷却中（ready=False）时应直接改用规则解析器，而不是空转。"""
        llm = _FakeParser(is_llm=True, result=None, ready=False)
        regex = _FakeParser(is_llm=False, result=_OK_RULE)
        svc = _service(llm, regex)

        assert svc._parser_or_fallback() is regex

class TestIdentifyFilesFallback:
    """下载器/同步源入库主干：LLM 失败必须由规则解析接手。"""

    def test_rule_parser_rescues_when_llm_returns_nothing(self, monkeypatch):
        llm = _FakeParser(is_llm=True, result=None)
        regex = _FakeParser(is_llm=False, result=_OK_RULE)
        svc = _service(llm, regex)

        seen: list[str] = []

        def fake_parse_batch(titles):
            svc._parser = llm
            seen.extend(titles)
            return [llm.parse(t) for t in titles]

        monkeypatch.setattr(svc, "_parser", llm)

        # 直接驱动批量回落逻辑：主解析器全失败 → 规则解析器补齐
        parsed_list = svc._parser.parse_batch(["Some.Movie.2024.1080p.mkv"])
        assert parsed_list == [None]

        fallback = svc._fallback_parser()
        assert fallback is regex
        fixed = regex.parse_batch(["Some.Movie.2024.1080p.mkv"])
        assert fixed[0] is _OK_RULE

    def test_real_regex_parser_parses_typical_filename(self):
        """真实 RegexParser 对规范命名可直接解析，证明回落是有意义的。"""
        from app.media.parser.regex import RegexParser

        parsed = RegexParser().parse("Some.Movie.2024.1080p.BluRay.x264-GROUP.mkv")
        assert parsed is not None
        assert parsed.year == "2024"
        assert parsed.resource_pix

    def test_real_regex_parser_parses_episode_filename(self):
        from app.media.parser.regex import RegexParser

        parsed = RegexParser().parse("Some.Show.S02E05.1080p.WEB-DL.mkv")
        assert parsed is not None
        assert parsed.season == 2
        assert parsed.episode == 5

class TestServiceWiring:
    @staticmethod
    def _fake_settings(monkeypatch):
        import app.media.service as service_module

        fake = MagicMock()
        fake.get.side_effect = lambda key: {"enabled": True, "media_recognizer_enabled": True} if key == "agent" else {}
        monkeypatch.setattr(service_module, "settings", fake)

    def test_primary_parser_is_local_rules_even_when_llm_ready(self, monkeypatch):
        """AI 识别只做兜底：即使 LLM 已启用且就绪，主解析器仍是本地规则。

        真实故障：LLM 作为主解析器时，同一批文件得到不一致的中文标题
        （「伟大的长征 / 天下长征 / 万里长征 / 长征」），其中一个命中了同名的
        其它作品，同一部剧因此在媒体库里被拆成两个条目。规则解析是确定性的。
        """
        self._fake_settings(monkeypatch)
        llm = _FakeParser(is_llm=True, result=_OK_RULE)
        regex = _FakeParser(is_llm=False, result=None)
        svc = MediaService.__new__(MediaService)
        svc._llm_parser = llm
        svc._regex_parser = regex

        assert svc._build_parser() is regex

    def test_llm_is_the_fallback_when_ready(self, monkeypatch):
        """规则不可信时，LLM 作为兜底可用。"""
        self._fake_settings(monkeypatch)
        llm = _FakeParser(is_llm=True, result=_OK_RULE)
        svc = MediaService.__new__(MediaService)
        svc._llm_parser = llm
        svc._regex_parser = _FakeParser(is_llm=False, result=None)
        svc._parser = svc._build_parser()

        assert svc._fallback_parser() is llm

    def test_no_fallback_when_llm_not_ready(self, monkeypatch):
        self._fake_settings(monkeypatch)
        regex = _FakeParser(is_llm=False, result=_OK_RULE)
        svc = MediaService.__new__(MediaService)
        svc._llm_parser = _FakeParser(is_llm=True, result=None, ready=False)
        svc._regex_parser = regex
        svc._parser = svc._build_parser()

        assert svc._fallback_parser() is None

class TestRecognizerCooldown:
    """连续调用异常后熔断，避免一批文件逐条撞同一个 429。"""

    def _recognizer(self, raising=True):
        from app.agent.agents.media_recognizer import MediaRecognizer

        svc = MagicMock()
        svc.ready = True

        def structured_chat(**kwargs):
            raise RuntimeError("429 用量上限")

        svc.structured_chat.side_effect = structured_chat
        return MediaRecognizer(svc=svc), svc

    def test_cooldown_after_repeated_failures(self):
        from app.agent.agents.media_recognizer import _FAILURE_THRESHOLD

        rec, svc = self._recognizer()
        for _ in range(_FAILURE_THRESHOLD):
            assert rec.recognize("a.mkv") is None

        assert rec.in_cooldown is True
        assert rec.ready is False
        calls_before = svc.structured_chat.call_count

        # 冷却期内不再发起请求
        assert rec.recognize("b.mkv") is None
        assert svc.structured_chat.call_count == calls_before

    def test_batch_short_circuits_in_cooldown(self):
        from app.agent.agents.media_recognizer import _FAILURE_THRESHOLD

        rec, svc = self._recognizer()
        for _ in range(_FAILURE_THRESHOLD):
            rec.recognize("a.mkv")

        assert rec.recognize_batch(["x.mkv", "y.mkv"]) == [None, None]

    def test_single_failure_does_not_cooldown(self):
        rec, _ = self._recognizer()
        rec.recognize("a.mkv")
        assert rec.in_cooldown is False
        assert rec.ready is True

    def test_success_resets_streak(self):
        from app.agent.agents.media_recognizer import _FAILURE_THRESHOLD

        rec, svc = self._recognizer()
        for _ in range(_FAILURE_THRESHOLD - 1):
            rec.recognize("a.mkv")
        assert rec.in_cooldown is False

        # 成功后计数清零，再失败不会立刻熔断
        from app.agent.agents.media_recognizer import MediaResult

        svc.structured_chat.side_effect = None
        svc.structured_chat.return_value = MediaResult(title_en="Movie", title_cn=None)
        assert rec.recognize("ok.mkv") is not None
        assert rec.in_cooldown is False

@pytest.mark.parametrize(
    "name",
    [
        "Some.Movie.2024.1080p.BluRay.x264-GROUP.mkv",
        "Show.S01E02.2160p.WEB-DL.mkv",
        "国产剧.第05集.1080p.mkv",
    ],
)
def test_rule_parser_covers_common_names(name):
    from app.media.parser.regex import RegexParser

    assert RegexParser().parse(name) is not None
