"""批量识别回归测试：模型返回裸数组时不得让整批结果丢失。

真实故障链（运行日志）：

    WARNING AgentService 结构化解析失败: 1 validation error for BatchResult
      Input should be a valid dictionary or instance of BatchResult
      [type=model_type, input_value=[{'title_en': 'Sample Title One II', ...}], input_type=list]
    WARNING MediaRecognizer 识别失败或返回空结果

LLM 识别内容完全正确，只是把顶层返回成 JSON 数组 `[{...}, ...]`，而 BatchResult
要求包装对象 `{"items": [...]}` → 校验失败 → structured_chat 返回 None →
`batch_results` 为空 → 整批 100 条全部变成未识别。更糟的是 structured_chat
吞掉了异常，`recognize_batch` 的 except 兜底分支根本不会执行。
"""

from app.agent.agents.media_recognizer import (
    MAX_BATCH_SIZE,
    BatchResult,
    MediaRecognizer,
    MediaResult,
)

BARE_ARRAY_PAYLOAD = [
    {"title_en": "Sample Title One II", "title_cn": "示例作品一II", "year": 2003, "type": "movie"},
    {"title_en": "The Sample Title Two Rises", "title_cn": "示例作品乙", "year": 2012, "type": "movie"},
]


class TestBatchResultShapeTolerance:
    def test_bare_array_is_wrapped(self):
        """核心回归：裸数组必须先被归一化，再进入校验。"""
        result = BatchResult.model_validate(BARE_ARRAY_PAYLOAD)
        assert [item.title_cn for item in result.items if item] == ["示例作品一II", "示例作品乙"]

    def test_wrapped_object_still_works(self):
        result = BatchResult.model_validate({"items": BARE_ARRAY_PAYLOAD})
        assert len(result.items) == 2

    def test_alias_single_key_object(self):
        result = BatchResult.model_validate({"results": BARE_ARRAY_PAYLOAD})
        assert [item.year for item in result.items if item] == [2003, 2012]

    def test_alias_with_extra_scalar_keys(self):
        """数组别名键 + 额外标量键（如 total）也应能提取。"""
        result = BatchResult.model_validate({"results": BARE_ARRAY_PAYLOAD, "total": 2})
        assert len(result.items) == 2

    def test_ambiguous_aliases_not_guessed(self):
        """两个数组别名键并存时无法判断，不猜（保持空结果，交由上层重试）。"""
        result = BatchResult.model_validate({"results": BARE_ARRAY_PAYLOAD, "data": BARE_ARRAY_PAYLOAD})
        assert result.items == []

    def test_null_and_junk_items_keep_alignment(self):
        """个别元素为 null / 字符串时降级为 None，绝不错位。"""
        payload = [
            {"title_cn": "示例作品一II"},
            None,
            "garbage",
            {"title_cn": "示例作品三3"},
        ]
        result = BatchResult.model_validate(payload)
        assert len(result.items) == 4
        assert result.items[0] is not None
        assert result.items[1] is None
        assert result.items[2] is None
        assert result.items[3] is not None
        assert result.items[3].title_cn == "示例作品三3"

    def test_empty_array(self):
        assert BatchResult.model_validate([]).items == []


class TestMediaResultShapeTolerance:
    def test_single_item_wrapped_in_array(self):
        result = MediaResult.model_validate([{"title_cn": "示例影片", "year": 2017}])
        assert result.title_cn == "示例影片"
        assert result.year == 2017

    def test_plain_object_unaffected(self):
        assert MediaResult.model_validate({"title_cn": "示例影片"}).title_cn == "示例影片"


class _FakeSvc:
    """模拟 AgentService：结构化输出解析失败时返回 None（不抛异常）。"""

    def __init__(self, batch_handler=None, single_handler=None):
        self.ready = True
        self._batch_handler = batch_handler
        self._single_handler = single_handler
        self.batch_requests: list[int] = []
        self.single_requests: list[str] = []

    @staticmethod
    def _count_filenames(content: str) -> int:
        return sum(1 for line in content.splitlines() if line.strip().startswith("["))

    def structured_chat(self, messages, system_prompt="", response_model=None, temperature=0.3, append_schema=True):
        content = messages[0]["content"]
        if response_model is BatchResult:
            count = self._count_filenames(content)
            self.batch_requests.append(count)
            return self._batch_handler(count) if self._batch_handler else None
        self.single_requests.append(content)
        return self._single_handler(content) if self._single_handler else None


def _filenames(n: int) -> list[str]:
    return [f"Some.Movie.{i}.2020.1080p.BluRay.x264-GROUP.mkv" for i in range(n)]


class TestRecognizeBatchResilience:
    def test_bare_array_from_llm_is_accepted(self):
        """LLM 返回裸数组时，整批识别结果必须保留。"""
        svc = _FakeSvc(
            batch_handler=lambda count: BatchResult.model_validate(
                [{"title_cn": f"影片{c}", "year": 2000 + c, "type": "movie"} for c in range(count)]
            )
        )
        results = MediaRecognizer(svc).recognize_batch(_filenames(5), batch_size=5)
        assert len(results) == 5
        assert all(r is not None for r in results)
        assert [r.title_cn for r in results if r] == ["影片0", "影片1", "影片2", "影片3", "影片4"]

    def test_parse_failure_falls_back_to_split_and_single(self):
        """structured_chat 返回 None（解析失败）时必须兜底，而不是整批作废。"""
        svc = _FakeSvc(
            batch_handler=lambda _count: None,
            single_handler=lambda name: MediaResult(title_cn=f"识别:{name[:12]}", type="movie"),
        )
        results = MediaRecognizer(svc).recognize_batch(_filenames(8), batch_size=8)
        assert len(results) == 8
        assert all(r is not None for r in results)
        # 递归是深度优先：8 → 4 → 2+2 → 4 → 2+2，共 7 次批量请求 + 8 次单条识别
        assert sorted(svc.batch_requests, reverse=True) == [8, 4, 4, 2, 2, 2, 2]
        assert len(svc.single_requests) == 8

    def test_truncated_batch_result_triggers_split(self):
        """结果数量远少于输入（输出截断）时按拆分重试，避免大批量条目被判未识别。"""
        svc = _FakeSvc(
            batch_handler=lambda count: BatchResult.model_validate(
                [{"title_cn": f"影片{c}"} for c in range(max(1, count // 4))]
            )
        )
        results = MediaRecognizer(svc).recognize_batch(_filenames(8), batch_size=8)
        assert len(results) == 8, "结果必须与输入等长，保持下标对齐"
        assert svc.batch_requests[0] == 8, "整批先试一次"
        assert sorted(svc.batch_requests, reverse=True) == [8, 4, 4, 2, 2, 2, 2], "截断的整批应逐级拆分重试"
        assert sum(1 for r in results if r is not None) == 4, "拆分后识别成功的条目必须保留"

    def test_batch_size_is_capped(self):
        """配置 batch_size=100 时按上限分批，避免长数组输出跑偏。"""
        svc = _FakeSvc(
            batch_handler=lambda count: BatchResult.model_validate([{"title_cn": "x"} for _ in range(count)])
        )
        MediaRecognizer(svc).recognize_batch(_filenames(100), batch_size=100)
        assert max(svc.batch_requests) == MAX_BATCH_SIZE
        assert sum(svc.batch_requests) == 100

    def test_not_ready_returns_none_list(self):
        svc = _FakeSvc()
        svc.ready = False
        assert MediaRecognizer(svc).recognize_batch(_filenames(3)) == [None, None, None]

    def test_empty_input(self):
        svc = _FakeSvc()
        assert MediaRecognizer(svc).recognize_batch([]) == []


class _StubProvider:
    """最小 Provider：直接把预设文本当成模型输出返回。"""

    def __init__(self, payload: str):
        self._payload = payload

    def chat(self, messages, system_prompt="", temperature=0.3, response_format=None, reasoning=None):
        return self._payload


class TestStructuredChatProductionFailure:
    """复现运行日志里的那条失败：走真实 AgentService.structured_chat 链路。"""

    @staticmethod
    def _service(payload: str):
        from app.agent.service import AgentService

        svc = AgentService()
        svc._enabled = True
        svc._provider = _StubProvider(payload)
        svc._fallbacks = []
        return svc

    def test_bare_json_array_no_longer_breaks_batch_parse(self):
        payload = (
            '[{"title_en": "Sample Title One II", "title_cn": "示例作品一II", "year": 2003, "type": "movie"},'
            ' {"title_en": "The Sample Title Two Rises", "title_cn": "示例作品乙", "year": 2012, '
            '"type": "movie"}]'
        )
        svc = self._service(payload)
        result = svc.structured_chat(
            messages=[{"role": "user", "content": "[0] a.mkv\n[1] b.mkv"}],
            system_prompt="批量识别",
            response_model=BatchResult,
        )
        assert result is not None, "裸数组不应再导致整批解析失败"
        assert [item.title_cn for item in result.items if item] == ["示例作品一II", "示例作品乙"]

    def test_unrecognizable_payload_still_returns_none(self):
        """真正的坏输出（非 JSON）仍返回 None，由上层拆分重试兜底。"""
        svc = self._service("抱歉，我无法识别这些文件名。")
        assert svc.structured_chat(messages=[{"role": "user", "content": "x"}], response_model=BatchResult) is None
