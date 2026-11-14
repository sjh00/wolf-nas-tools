"""过滤规则：排除项语义 + 剧集「只下整季」门禁.

两个真实缺陷：
1. 多行 EXCLUDE 只有「全部命中」才排除，等于几乎不生效（REMUX/3D 照样下）。
2. 剧集订阅缺「只下整季」的能力，退化成逐集下载。
"""

import pytest

from app.domain.media_types import ProviderMediaType
from app.indexer.core.filter_engine import (
    IndexerFilterEngine,
    is_complete_only_group,
    looks_like_complete_pack,
)
from app.media import meta_info


def _mi(title: str, mtype: ProviderMediaType = ProviderMediaType.SERIES):
    info = meta_info(title=title, mtype=mtype)
    info.org_string = title
    info.size = 3 * 1024**3
    return info


class TestExcludeSemantics:
    """任一排除项命中即排除。"""

    def test_single_exclude_rejects(self):
        mi = _mi("Some.Show.S01.1080p.REMUX.HEVC-GRP")
        filters = [{"pri": 1, "include": ["1080p"], "exclude": ["REMUX"]}]
        ok, _, _ = IndexerFilterEngine.check_rules(mi, {"name": "g"}, filters)
        assert ok is False

    def test_multi_exclude_rejects_on_first_hit(self):
        """多行排除：命中任意一行就排除（旧实现要求全部命中才排除）。"""
        mi = _mi("Some.Show.S01.1080p.REMUX.HEVC-GRP")
        filters = [{"pri": 1, "include": ["1080p"], "exclude": ["\\b3D\\b", "REMUX", "minibd"]}]
        ok, _, _ = IndexerFilterEngine.check_rules(mi, {"name": "g"}, filters)
        assert ok is False

    def test_multi_exclude_passes_when_none_hit(self):
        mi = _mi("Some.Show.S01.1080p.WEB-DL.HEVC-GRP")
        filters = [{"pri": 1, "include": ["1080p"], "exclude": ["\\b3D\\b", "REMUX", "minibd"]}]
        ok, _, _ = IndexerFilterEngine.check_rules(mi, {"name": "g"}, filters)
        assert ok is True


class TestCompleteOnlyGroupFlag:
    def test_flag_parsed_from_note_json(self):
        assert is_complete_only_group({"note": '{"complete_only": true}'}) is True
        assert is_complete_only_group({"note": '{"complete_only": false}'}) is False

    def test_missing_or_bad_note_is_not_complete_only(self):
        assert is_complete_only_group({}) is False
        assert is_complete_only_group({"note": None}) is False
        assert is_complete_only_group({"note": ""}) is False
        assert is_complete_only_group({"note": "不是JSON"}) is False
        assert is_complete_only_group({"note": "[1,2]"}) is False


class TestLooksLikeCompletePack:
    @pytest.mark.parametrize(
        "title",
        [
            "Some.Show.S01.1080p.WEB-DL.HEVC-GRP",          # 只有季号
            "Some Show Complete Series 1080p",
            "某剧 全集 1080p WEB-DL",
            "Some.Show.S01E01-E10.1080p.WEB-DL",            # 集号区间
            "Some.Show.S01-S03.1080p.WEB-DL",               # 跨季区间
        ],
    )
    def test_pack_detected(self, title):
        assert looks_like_complete_pack(_mi(title)) is True

    @pytest.mark.parametrize(
        "title",
        [
            "Some.Show.S01E05.1080p.WEB-DL.HEVC-GRP",
            "Some.Show.S02E08.2160p.WEB-DL",
        ],
    )
    def test_single_episode_is_not_pack(self, title):
        assert looks_like_complete_pack(_mi(title)) is False


class TestCompleteOnlyGate:
    GROUP = {"name": "只下整季", "note": '{"complete_only": true}'}

    def test_single_episode_rejected(self):
        mi = _mi("Some.Show.S01E05.1080p.WEB-DL.HEVC-GRP")
        filters = [{"pri": 1, "include": ["1080p"]}]
        ok, _, name = IndexerFilterEngine.check_rules(mi, self.GROUP, filters)
        assert ok is False
        assert name == "只下整季"

    def test_season_pack_accepted(self):
        mi = _mi("Some.Show.S01.1080p.WEB-DL.HEVC-GRP")
        filters = [{"pri": 1, "include": ["1080p"]}]
        ok, _, _ = IndexerFilterEngine.check_rules(mi, self.GROUP, filters)
        assert ok is True

    def test_movie_unaffected_by_gate(self):
        """电影订阅不受整季门禁影响。"""
        mi = _mi("Some.Movie.2019.1080p.BluRay.x264-GRP", ProviderMediaType.MOVIE)
        filters = [{"pri": 1, "include": ["1080p"]}]
        ok, _, _ = IndexerFilterEngine.check_rules(mi, self.GROUP, filters)
        assert ok is True

    def test_group_without_flag_allows_single_episode(self):
        mi = _mi("Some.Show.S01E05.1080p.WEB-DL.HEVC-GRP")
        filters = [{"pri": 1, "include": ["1080p"]}]
        ok, _, _ = IndexerFilterEngine.check_rules(mi, {"name": "日常"}, filters)
        assert ok is True
