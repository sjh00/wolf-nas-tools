"""AI 识别质量与成本优化回归测试。

覆盖四类问题：
1. 串味：单条结果里拼接了多个作品的片名（运行日志真实出现过）
2. 错位：批量结果漏条/乱序时，后续条目被记到别人身上
3. 重复调用：同一文件名在一批里重复出现时重复请求 LLM
4. 无效 token：提示词已列字段，却还追加完整 JSON Schema
"""

from app.agent.agents.media_recognizer import (
    BatchResult,
    MediaRecognizer,
    MediaResult,
    _pick_primary_title,
)


class _Svc:
    def __init__(self, batch_handler=None, single_handler=None, captured=None):
        self.ready = True
        self._batch_handler = batch_handler
        self._single_handler = single_handler
        self.captured = captured if captured is not None else {}
        self.batch_calls: list[int] = []
        self.single_calls: list[str] = []

    def structured_chat(self, messages, system_prompt="", response_model=None, temperature=0.3, append_schema=True):
        content = messages[0]["content"]
        self.captured.setdefault("kwargs", []).append(
            {"temperature": temperature, "append_schema": append_schema, "system_prompt_len": len(system_prompt)}
        )
        if response_model is BatchResult:
            count = sum(1 for line in content.splitlines() if line.strip().startswith("["))
            self.batch_calls.append(count)
            return self._batch_handler(count) if self._batch_handler else None
        self.single_calls.append(content)
        return self._single_handler(content) if self._single_handler else None


class TestSwallowedTitles:
    """片名被拼接时只保留属于当前文件的那一段。"""

    def test_split_multi_title_by_overlap(self):
        value = "示例作品甲 / 示例作品乙 / 示例作品丙 / 示例作品丁 / 示例作品戊"
        picked = _pick_primary_title(value, "Some.Movie.2006.1080p.BluRay.x264-GROUP.mkv")
        # 英文文件名里没有中文片名的字符，重合度全为 0 → 保留第一段（模型通常先写主线）
        assert picked == "示例作品甲"

    def test_picks_segment_present_in_filename(self):
        value = "Sample Title One / 示例作品一 / 示例作品丙"
        assert _pick_primary_title(value, "Infernal.Affairs.2002.1080p.mkv") == "Sample Title One"

    def test_keeps_legitimate_bilingual_title(self):
        """两段的双语片名（含 /）不应被切断。"""
        assert _pick_primary_title("Spider-Man/蜘蛛侠", "Spider-Man.2002.mkv") == "Spider-Man/蜘蛛侠"

    def test_recognize_sanitizes_swallowed_title(self):
        svc = _Svc(
            single_handler=lambda _name: MediaResult(title_cn="示例作品甲 / 示例作品乙 / 示例作品丙", type="movie")
        )
        result = MediaRecognizer(svc).recognize("Some.Movie.2006.mkv")
        assert result is not None
        assert result.title_cn == "示例作品甲"
        assert "/" not in (result.title_cn or "")

    def test_drops_identical_cn_en(self):
        svc = _Svc(single_handler=lambda _name: MediaResult(title_cn="示例影片", title_en="示例影片"))
        result = MediaRecognizer(svc).recognize("Sample.Movie.2017.mkv")
        assert result is not None
        assert result.title_cn == "示例影片"
        assert result.title_en is None


class TestIndexAlignment:
    """批量结果带 index 时按 index 对齐，防止漏条导致整体错位。"""

    def test_items_reordered_by_index(self):
        payload = {
            "items": [
                {"index": 2, "title_cn": "第三部"},
                {"index": 0, "title_cn": "第一部"},
                {"index": 1, "title_cn": "第二部"},
            ]
        }
        result = BatchResult.model_validate(payload)
        assert [i.title_cn for i in result.items if i] == ["第一部", "第二部", "第三部"]

    def test_missing_item_with_index_keeps_alignment(self):
        """模型漏掉 index=1 时，index=2 的结果不能被塞给第 2 条文件名。"""
        svc = _Svc(
            batch_handler=lambda _count: BatchResult.model_validate(
                {"items": [{"index": 0, "title_cn": "A"}, {"index": 2, "title_cn": "C"}]}
            ),
            single_handler=lambda name: MediaResult(title_cn=f"S:{name[:6]}"),
        )
        results = MediaRecognizer(svc).recognize_batch(["a.mkv", "b.mkv", "c.mkv"], batch_size=3)
        assert len(results) == 3
        titles = [item.title_cn if item else None for item in results]
        assert titles[0] == "A"
        assert (titles[1] or "").startswith("S:"), "漏条应走单条兜底而非错位"
        assert titles[2] == "C"

    def test_without_index_falls_back_to_order(self):
        result = BatchResult.model_validate([{"title_cn": "甲"}, {"title_cn": "乙"}])
        assert [i.title_cn for i in result.items if i] == ["甲", "乙"]


class TestDeduplication:
    """同一文件名重复出现时只请求一次 LLM。"""

    def test_duplicate_filenames_are_requested_once(self):
        svc = _Svc(
            batch_handler=lambda count: BatchResult.model_validate(
                [{"title_cn": f"影片{c}", "index": c} for c in range(count)]
            )
        )
        names = ["same.mkv", "same.mkv", "other.mkv", "same.mkv"]
        results = MediaRecognizer(svc).recognize_batch(names, batch_size=10)
        assert len(results) == 4
        assert svc.batch_calls == [2], "去重后只应发 2 条"
        titles = [item.title_cn if item else None for item in results]
        # 展开后相同文件名得到相同结果
        assert titles[0] == titles[1] == titles[3]
        assert titles[2] != titles[0]


class TestTokenSaving:
    """提示词已描述结构时不再追加完整 JSON Schema。"""

    def test_batch_request_skips_schema_and_uses_zero_temperature(self):
        svc = _Svc(batch_handler=lambda count: BatchResult.model_validate([{"title_cn": "x"} for _ in range(count)]))
        MediaRecognizer(svc).recognize_batch(["a.mkv", "b.mkv"], batch_size=2)
        batch_kwargs = svc.captured["kwargs"][0]
        assert batch_kwargs["append_schema"] is False
        assert batch_kwargs["temperature"] == 0.0

    def test_single_request_uses_zero_temperature_but_keeps_schema(self):
        svc = _Svc(single_handler=lambda _n: MediaResult(title_cn="示例影片"))
        MediaRecognizer(svc).recognize("Sample.Movie.2017.mkv")
        kwargs = svc.captured["kwargs"][0]
        assert kwargs["temperature"] == 0.0
        assert kwargs["append_schema"] is True, "单条没有逐字段提示词，仍需 schema 约束"

    def test_batch_prompt_asks_for_index(self):
        svc = _Svc(batch_handler=lambda count: BatchResult.model_validate([{"title_cn": "x"} for _ in range(count)]))
        MediaRecognizer(svc).recognize_batch(["a.mkv"], batch_size=1)
        # 单条走 single 路径；用两条确认批量提示词里要求回传 index
        svc2 = _Svc(batch_handler=lambda count: BatchResult.model_validate([{"title_cn": "x"} for _ in range(count)]))
        MediaRecognizer(svc2).recognize_batch(["a.mkv", "b.mkv"], batch_size=2)
        assert svc2.batch_calls == [2]
