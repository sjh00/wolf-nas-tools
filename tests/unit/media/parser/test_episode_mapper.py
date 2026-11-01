"""EpisodeMapper 季集映射 — 合并季（动漫按季度连贯编号）回退测试.

回归场景：药屋少女的呢喃（TMDB 220542）在 TMDB 上是合并季 S01 共 60 集，
发布组按季度编号 S03E01 = 绝对第 49 集。此前 map_auto 对 season>1 且 episode≤26
只做"TMDB 是否已有该季"的快速检查，永远等不到 S03，直接放弃映射 → 订阅不到资源。
"""

from unittest.mock import MagicMock, patch

from app.media.parser.episode_mapper import EpisodeMapper

# TMDB 合并季：只有 S01，共 60 集（24 + 24 + 12）
MERGED_TMDB = {"id": 220542, "seasons": [{"season_number": 1, "episode_count": 60}]}
# 由 air_date 推断出的季块：S01E1-24 / S01E25-48 / S01E49-60
MERGED_BLOCKS = [(1, 1, 24), (2, 25, 48), (3, 49, 60)]


def _mapper(tv_info, blocks):
    tmdb = MagicMock()
    tmdb.get_tmdb_info.return_value = tv_info
    mapper = EpisodeMapper(tmdb_lookup=tmdb)
    patcher = patch.object(EpisodeMapper, "_fetch_blocks", return_value=blocks)
    patcher.start()
    return mapper, patcher


class TestMergedSeasonFallback:
    """TMDB 只有合并 S01 时，发布组的季度编号应映射到绝对集号."""

    def test_season_beyond_tmdb_falls_back_to_blocks(self):
        mapper, patcher = _mapper(MERGED_TMDB, MERGED_BLOCKS)
        try:
            assert mapper.map_auto(220542, 3, 1) == (1, 49)
            assert mapper.map_auto(220542, 3, 2) == (1, 50)
            assert mapper.map_auto(220542, 2, 1) == (1, 25)
        finally:
            patcher.stop()

    def test_range_maps_both_ends(self):
        mapper, patcher = _mapper(MERGED_TMDB, MERGED_BLOCKS)
        try:
            assert mapper.map_auto(220542, 3, 1, 3) == (1, 49, 1, 51)
        finally:
            patcher.stop()

    def test_canonical_coordinates_untouched(self):
        """TMDB 已有该季且集号在范围内 → 无需映射."""
        mapper, patcher = _mapper(MERGED_TMDB, MERGED_BLOCKS)
        try:
            assert mapper.map_auto(220542, 1, 49) is None
            assert mapper.map_auto(220542, 1, 25) is None
        finally:
            patcher.stop()

    def test_normal_multi_season_show_not_remapped(self):
        """无法推断季块（正常多季剧）→ 不猜测、不映射."""
        normal = {
            "id": 1396,
            "seasons": [
                {"season_number": 1, "episode_count": 24},
                {"season_number": 2, "episode_count": 24},
            ],
        }
        mapper, patcher = _mapper(normal, None)
        try:
            assert mapper.map_auto(1396, 3, 1) is None
        finally:
            patcher.stop()

    def test_out_of_range_source_season_not_mapped(self):
        """源季号超过推断季数 → 跳过，避免误映射."""
        mapper, patcher = _mapper(MERGED_TMDB, [(1, 1, 24)])
        try:
            assert mapper.map_auto(220542, 3, 1) is None
        finally:
            patcher.stop()
