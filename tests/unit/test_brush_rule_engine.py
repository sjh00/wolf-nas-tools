"""BrushRuleEngine 删种/停种规则回归测试."""

from app.domain.engine.brush_rule_engine import BrushRuleEngine
from app.domain.enums import BrushDeleteType, BrushStopType, SwitchState


class TestCheckRemoveRule:
    def test_seedtime_or_mode(self):
        ok, typ = BrushRuleEngine.check_remove_rule(
            {"mode": "or", "time": "gt#1"},
            {"seeding_time": 7200, "ratio": 1.0, "uploaded": 0, "torrent_attr": {}},
        )
        assert ok is True
        assert typ == BrushDeleteType.SEEDTIME

    def test_hr_value_available_in_and_mode(self):
        ok, typ = BrushRuleEngine.check_remove_rule(
            {"mode": "and", "hr": "HR", "time": "gt#1"},
            {
                "seeding_time": 7200,
                "ratio": 1.0,
                "uploaded": 0,
                "torrent_attr": {"hr": True},
            },
        )
        assert ok is True
        assert BrushDeleteType.HR in (typ if isinstance(typ, list) else [typ])
        assert BrushDeleteType.SEEDTIME in (typ if isinstance(typ, list) else [typ])

    def test_avg_upspeed_uses_kb_multiplier(self):
        # 50 KB/s < 100 KB/s 应触发；若误用 GB 倍数则永远不触发
        ok, typ = BrushRuleEngine.check_remove_rule(
            {"mode": "or", "avg_upspeed": "lt#100"},
            {
                "seeding_time": 0,
                "ratio": 0,
                "uploaded": 0,
                "avg_upspeed": 50 * 1024,
                "torrent_attr": {},
            },
        )
        assert ok is True
        assert typ == BrushDeleteType.AVGUPSPEED

    def test_cur_upspeed_alias(self):
        ok, typ = BrushRuleEngine.check_remove_rule(
            {"mode": "or", "cur_upspeed": "lt#100"},
            {
                "seeding_time": 0,
                "ratio": 0,
                "uploaded": 0,
                "upspeed": 10 * 1024,
                "torrent_attr": {},
            },
        )
        assert ok is True
        assert typ == BrushDeleteType.UPSPEED


class TestCheckStopRule:
    def test_stop_avg_upspeed_kb(self):
        ok, typ = BrushRuleEngine.check_stop_rule(
            {"avg_upspeed": "lt#100", "stopfree": SwitchState.OFF.value},
            {
                "ratio": 0,
                "uploaded": 0,
                "seeding_time": 0,
                "avg_upspeed": 50 * 1024,
                "free": True,
            },
        )
        assert ok is True
        assert typ == BrushStopType.AVGUPSPEED
