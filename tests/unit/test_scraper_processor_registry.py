"""刮削后处理器注册表测试."""

from app.media.scraper.processor_registry import ScraperProcessorRegistry


def test_processors_run_and_unregister_by_plugin():
    registry = ScraperProcessorRegistry()
    calls = []
    registry.register("plugin-a", "snapshot", lambda snapshot: calls.append(("snapshot", snapshot)))
    registry.register("plugin-a", "poster", lambda path, snapshot: calls.append(("poster", path)) or "right")
    registry.register("plugin-a", "watermark", lambda target, snapshot: calls.append(("watermark", target)) or 2)

    registry.enrich_snapshot("s1")
    assert registry.process_poster("p1", "s1") == ["right"]
    assert registry.process_watermark("d1", "s1") == 2
    assert calls == [("snapshot", "s1"), ("poster", "p1"), ("watermark", "d1")]

    registry.unregister_plugin("plugin-a")
    registry.enrich_snapshot("s2")
    assert registry.process_poster("p2", "s2") == []
    assert registry.process_watermark("d2", "s2") == 0
