"""豆瓣榜单订阅：发行年份守门 + 榜单类型推断.

榜单里的老片多半是识别成了错作品，或者老片重置版（发行年仍是原年份）。
自动订阅必须挡住这类条目，否则会把完全无关的老片订阅进来。
"""

from datetime import datetime

import pytest

from app.domain.media_types import ProviderMediaType
from app.plugin_framework.builtin_plugins.doubanrank.backend.plugin import DoubanRankPlugin


class TestInferTypeFromAddr:
    @pytest.mark.parametrize(
        "addr",
        [
            "https://rsshub.app/douban/movie/weekly/tv_hot",
            "https://rsshub.app/douban/movie/weekly/show_domestic",
            "http://rsshub.example.com/douban/tv/hot",
            "http://example.com/douban/show-cn",
        ],
    )
    def test_tv_rank(self, addr):
        assert DoubanRankPlugin._infer_type_from_addr(addr) == ProviderMediaType.SERIES

    @pytest.mark.parametrize(
        "addr",
        [
            "https://rsshub.app/douban/movie/ustop",
            "https://rsshub.app/douban/movie/weekly",
            "http://rsshub.example.com/douban/movie/weekly/movie_real_time_hotest",
            "https://rsshub.app/douban/movie/weekly/movie_top250",
        ],
    )
    def test_movie_rank(self, addr):
        assert DoubanRankPlugin._infer_type_from_addr(addr) == ProviderMediaType.MOVIE

    def test_empty_addr_returns_none(self):
        assert DoubanRankPlugin._infer_type_from_addr("") is None


class TestMinYear:
    def test_default_two_years_keeps_current_and_last(self):
        """year_limit=2 → 今年与去年。"""
        this_year = datetime.now().year
        assert DoubanRankPlugin._min_year(2) == this_year - 1

    def test_three_years(self):
        this_year = datetime.now().year
        assert DoubanRankPlugin._min_year(3) == this_year - 2

    @pytest.mark.parametrize("bad", [0, -5])
    def test_non_positive_falls_back_to_one_year(self, bad):
        """配置成 0 或负数时至少保留今年，不能把阈值推到未来。"""
        assert DoubanRankPlugin._min_year(bad) == datetime.now().year
