"""旧版「只订阅不搜索」哨兵 `#dontuse` 的兼容处理。

旧版本用 `search_sites = ["#dontuse"]` 表达「只走 RSS、不做站点搜索」。
v4 改用空列表表达同一语义，但库里仍留有带该标记的订阅。不识别它会被当成
一个不存在的站点名：搜索零站点（行为碰巧正确），但日志刷「站点列表为空」、
前端把这个假站点显示给用户，排查时极易被误判成站点配置丢失。
"""

import pytest

from app.domain.media_types import ProviderMediaType
from app.services.subscribe.management.query_service import _filter_sites, _load_sites
from app.services.subscribe.management.utils import (
    DONT_USE_SENTINEL,
    normalize_sites,
)
from app.services.subscribe.strategies.base_search import BaseSearchStrategy


class TestNormalizeSites:
    def test_sentinel_becomes_empty_list(self):
        """哨兵等价于「一个站点都不搜索」。"""
        assert normalize_sites([DONT_USE_SENTINEL]) == []

    def test_sentinel_mixed_with_real_sites(self):
        """混写时只去掉哨兵，保留真实站点。"""
        assert normalize_sites([DONT_USE_SENTINEL, "HDSky", "panda"]) == ["HDSky", "panda"]

    def test_normal_sites_untouched(self):
        assert normalize_sites(["HDSky"]) == ["HDSky"]

    def test_none_still_none(self):
        assert normalize_sites(None) is None

    def test_empty_still_empty(self):
        assert normalize_sites([]) == []


class TestLoadSites:
    def test_sentinel_column_loads_as_empty(self):
        assert _load_sites('["#dontuse"]') == []

    def test_normal_column_loads(self):
        assert _load_sites('["HDSky","panda"]') == ["HDSky", "panda"]

    def test_null_column_is_unset(self):
        assert _load_sites(None) is None

    def test_filter_keeps_empty(self):
        """空列表经过白名单过滤仍然是空列表，不能被当成"未设置"。"""
        assert _filter_sites([], ["HDSky"]) == []


class TestEffectiveSearchSites:
    @pytest.fixture()
    def strategy(self):
        class _S(BaseSearchStrategy):
            def __init__(self, system_config):
                self._system_config = system_config

        return _S({"DefaultSubscribeSettingTV": {"search_sites": ["默认站点"]}})

    def test_sentinel_means_zero_sites_not_default(self, strategy):
        """核心：哨兵不能被回退成默认站点，否则老订阅会突然全站搜索。"""
        sites = strategy._get_effective_search_sites(
            {"search_sites": [DONT_USE_SENTINEL], "name": "旧订阅"},
            ProviderMediaType.SERIES,
        )

        assert sites == []

    def test_empty_still_zero_sites(self, strategy):
        sites = strategy._get_effective_search_sites(
            {"search_sites": [], "name": "新订阅"}, ProviderMediaType.SERIES
        )

        assert sites == []

    def test_unset_falls_back_to_default(self, strategy):
        sites = strategy._get_effective_search_sites(
            {"search_sites": None, "name": "未设置"}, ProviderMediaType.SERIES
        )

        assert sites == ["默认站点"]
