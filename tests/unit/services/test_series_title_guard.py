"""剧集记录被污染时不得反向覆盖订阅标题。

真实故障：TMDB 数字 ID 按类型分区，同一数字在电影与剧集下是两部作品。
历史数据里留下了「剧集别名指向电影作品」的记录（标题为那部电影、年份也是电影的），
订阅创建时采用剧集记录的母标题，于是订阅被改名成另一部电影，
而海报、简介、集数仍来自正确的剧集。

修复：标题不同 **且** 年份也不同的剧集记录视为污染，不采用其标题。
"""

from types import SimpleNamespace

import pytest

from app.services.series_service import SeriesService


def _series(title, year):
    return SimpleNamespace(TITLE=title, YEAR=year)


class TestAliasConflict:
    def test_polluted_alias_is_detected(self):
        """剧集记录是另一部电影（标题与年份都不同）→ 判定为污染。"""
        assert SeriesService._alias_conflicts(_series("Cavalcade d'amour", "1939"), "谷雨", "2026") is True

    def test_bilingual_title_same_year_is_fine(self):
        """同一作品的英文名搜索 + 中文母标题：年份相同，正常。"""
        assert SeriesService._alias_conflicts(_series("谷雨", "2026"), "The Silent Storm", "2026") is False

    def test_same_title_different_year_is_fine(self):
        """重拍/续作：标题相同但年份不同，母标题仍可复用。"""
        assert SeriesService._alias_conflicts(_series("谷雨", "1939"), "谷雨", "2026") is False

    def test_missing_year_does_not_conflict(self):
        """年份缺失时无法判定矛盾，保持原有行为。"""
        assert SeriesService._alias_conflicts(_series("Cavalcade d'amour", None), "谷雨", "2026") is False
        assert SeriesService._alias_conflicts(_series("Cavalcade d'amour", "1939"), "谷雨", None) is False

    def test_empty_title_does_not_conflict(self):
        assert SeriesService._alias_conflicts(_series("", "1939"), "谷雨", "2026") is False
        assert SeriesService._alias_conflicts(_series("谷雨", "1939"), "", "2026") is False


class TestSubscribeSeriesTitleGuard:
    """订阅侧同规则：剧集记录与识别结果矛盾时保留识别结果。"""

    @pytest.fixture()
    def svc(self):
        from app.services.subscribe.management.add_service import SubscribeAddService

        return SubscribeAddService.__new__(SubscribeAddService)

    def test_conflict_keeps_recognized_title(self, svc):
        resolution = SimpleNamespace(title="Cavalcade d'amour", year="1939")
        media = SimpleNamespace(title="谷雨", year="2026")
        assert svc._series_title_conflicts(resolution, media) is True

    def test_same_year_keeps_series_title(self, svc):
        resolution = SimpleNamespace(title="谷雨", year="2026")
        media = SimpleNamespace(title="The Silent Storm", year="2026")
        assert svc._series_title_conflicts(resolution, media) is False

    def test_punctuation_only_difference_not_conflict(self, svc):
        resolution = SimpleNamespace(title="The.Silent.Storm", year="2026")
        media = SimpleNamespace(title="The Silent Storm", year="2026")
        assert svc._series_title_conflicts(resolution, media) is False
