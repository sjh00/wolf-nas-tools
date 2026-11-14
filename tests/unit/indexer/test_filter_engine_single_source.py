"""过滤引擎必须只有一套判定逻辑。

历史上 services.filter_service.FilterRuleEngine 与
indexer.core.filter_engine.IndexerFilterEngine 各有一份几乎相同的实现，
同一个缺陷要在两处各修一遍（EXCLUDE 语义就是这样漏掉一次），
还出现过分歧（年份匹配一边精确、一边允许 ±1 年）。
现在服务侧只保留转调，这里锁住该约束。
"""

from app.domain.media_types import ProviderMediaType
from app.indexer.core.filter_engine import IndexerFilterEngine
from app.media import ReleaseGroupsMatcher, meta_info
from app.services.filter_service import FilterRuleEngine, FilterService


def _mi(title: str, mtype: ProviderMediaType = ProviderMediaType.SERIES):
    info = meta_info(title=title, mtype=mtype)
    info.org_string = title
    info.size = 3 * 1024**3
    info.upload_volume_factor = 1.0
    info.download_volume_factor = 1.0
    return info


class TestServiceEngineDelegates:
    """服务侧引擎不保留自己的实现。"""

    def test_check_rules_same_result(self):
        title = "Some.Show.S01E05.1080p.WEB-DL.HEVC-GRP"
        group = {"name": "g"}
        filters = [{"pri": 1, "include": ["1080p"], "exclude": ["REMUX"]}]
        a = FilterRuleEngine.check_rules(_mi(title), group, filters)
        b = IndexerFilterEngine.check_rules(_mi(title), group, filters)
        assert a == b

    def test_exclude_semantics_shared(self):
        """EXCLUDE 任一命中即排除——两个入口必须一致。"""
        title = "Some.Show.S01.1080p.REMUX.HEVC-GRP"
        group = {"name": "g"}
        filters = [{"pri": 1, "include": ["1080p"], "exclude": ["\\b3D\\b", "REMUX", "minibd"]}]
        assert FilterRuleEngine.check_rules(_mi(title), group, filters)[0] is False
        assert IndexerFilterEngine.check_rules(_mi(title), group, filters)[0] is False

    def test_complete_only_shared(self):
        group = {"name": "只整季", "note": '{"complete_only": true}'}
        filters = [{"pri": 1, "include": ["1080p"]}]
        single = "Some.Show.S01E05.1080p.WEB-DL.HEVC-GRP"
        pack = "Some.Show.S01.1080p.WEB-DL.HEVC-GRP"
        assert FilterRuleEngine.check_rules(_mi(single), group, filters)[0] is False
        assert IndexerFilterEngine.check_rules(_mi(single), group, filters)[0] is False
        assert FilterRuleEngine.check_rules(_mi(pack), group, filters)[0] is True
        assert IndexerFilterEngine.check_rules(_mi(pack), group, filters)[0] is True

    def test_torrent_filter_keeps_legacy_semantics(self):
        """RSS 自动化路径不启用音频/漫画/过小/仅免费守卫，行为与改造前一致。"""
        mi = _mi("Some.Show.S01E05.1080p.WEB-DL.HEVC-GRP")
        mi.size = 10 * 1024 * 1024  # 10MB，低于 min_filesize
        args = {"free": True}
        ok, _, _ = FilterRuleEngine.check_torrent_filter(mi, args, ReleaseGroupsMatcher())
        assert ok is True, "旧调用方不应因新增守卫被拒"

    def test_torrent_filter_guards_when_enabled(self):
        """索引器路径启用守卫：仅免费要求 + 无法判断促销时必须拒绝。"""
        mi = _mi("Some.Show.S01E05.1080p.WEB-DL.HEVC-GRP")
        ok, _, msg = IndexerFilterEngine.check_torrent_filter(mi, {"free": True})
        assert ok is False
        assert "免费" in msg


class TestNoDuplicateImplementation:
    def test_service_engine_has_no_own_rule_loop(self):
        """服务侧不应再出现规则匹配循环（转调即可）。"""
        import inspect

        src = inspect.getsource(FilterRuleEngine)
        assert "for filter_info in filters" not in src
        assert "IndexerFilterEngine.check_rules" in src

    def test_dead_sey_wrapper_removed_from_engine(self):
        """FilterRuleEngine 上的重复 SEY 实现已删除，服务侧改为直接委托。"""
        assert not hasattr(FilterRuleEngine, "is_torrent_match_sey")
        assert hasattr(FilterService, "is_torrent_match_sey")
