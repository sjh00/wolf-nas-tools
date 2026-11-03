"""Tests for app.utils.chinese_utils."""

import pytest

from app.utils.chinese_utils import to_simplified


class TestToSimplified:
    """Test suite for to_simplified utility."""

    def test_convert_traditional_to_simplified(self):
        assert to_simplified("繁體中文") == "繁体中文"

    def test_convert_hong_kong_to_simplified(self):
        assert to_simplified("髮型") == "发型"

    def test_already_simplified(self):
        assert to_simplified("简体中文") == "简体中文"

    def test_empty_string(self):
        assert to_simplified("") == ""

    def test_none_input(self):
        assert to_simplified(None) == ""

    def test_non_chinese_text(self):
        assert to_simplified("Hello World 123") == "Hello World 123"

    def test_mixed_text(self):
        assert to_simplified("電影 Movie 2024") == "电影 Movie 2024"

    @pytest.mark.parametrize(
        ("input_text", "expected"),
        [
            ("臺灣", "台湾"),
            ("繁體中文", "繁体中文"),
            ("髮型", "发型"),
            # 台湾用词（軟體→软件）不做词汇替换，只做字形转换。
            # tw2sp 的词汇替换与「台湾异体字规范化」绑定，后者会把已经是简体的
            # 常用字改错（么→幺、著→着、埠→端口），对媒体标题杀伤过大；
            # 本函数只服务于片名/人名，不需要 IT 术语的台湾用法替换。
            ("軟體", "软体"),
            ("作業系統", "作业系统"),
            ("資料庫", "资料库"),
        ],
    )
    def test_common_conversions(self, input_text, expected):
        assert to_simplified(input_text) == expected
