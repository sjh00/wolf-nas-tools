"""豆瓣 RSS 解析：条目 ID 与年份.

真实 RSSHub 输出（自建实例）：
    <title>可能的爱</title>
    <description>…标签：2026 / 韩国 / 剧情 爱情…</description>
    <link>https://www.douban.com/doubanapp/dispatch/movie/36847425</link>

旧正则 `/(\d+)/` 要求数字两侧都是斜杠，而这种 link 的数字在结尾，
永远匹配不到 → doubanid 恒空 → 退回标题裸搜 → 命中同名老片。
"""

import pytest

from app.plugin_framework.builtin_plugins.doubanrank.backend.plugin import DoubanRankPlugin


class TestParseDoubanId:
    @pytest.mark.parametrize(
        ("link", "expected"),
        [
            # RSSHub dispatch 形式：数字在结尾，无尾随斜杠（生产实际格式）
            ("https://www.douban.com/doubanapp/dispatch/movie/36847425", "36847425"),
            # 传统 subject 形式：尾随斜杠
            ("https://movie.douban.com/subject/1292052/", "1292052"),
            # 带查询串
            ("https://www.douban.com/doubanapp/dispatch/movie/37322586?dt_dapp=1", "37322586"),
            ("https://www.douban.com/doubanapp/dispatch/movie/37215318/", "37215318"),
        ],
    )
    def test_extracts_id(self, link, expected):
        assert DoubanRankPlugin._parse_douban_id(link) == expected

    @pytest.mark.parametrize("link", ["", None, "https://example.com/no-id", "https://x.com/12"])
    def test_returns_empty_when_absent(self, link):
        assert DoubanRankPlugin._parse_douban_id(link) == ""


class TestParseDoubanYear:
    @pytest.mark.parametrize(
        ("desc", "expected"),
        [
            ("<p>评分：8.7分</p><p>标签：2026 / 韩国 / 剧情 爱情 / 李沧东</p>", "2026"),
            ("标签：2025 / 埃及 / 剧情", "2025"),
            ("标签: 2024 / 中国大陆 / 悬疑", "2024"),
            ("标签：2022 / 日本 / 动画", "2022"),
        ],
    )
    def test_extracts_year(self, desc, expected):
        assert DoubanRankPlugin._parse_douban_year(desc) == expected

    @pytest.mark.parametrize("desc", ["", None, "没有标签字段", "<p>评分：8.0</p>"])
    def test_returns_empty_when_absent(self, desc):
        assert DoubanRankPlugin._parse_douban_year(desc) == ""
