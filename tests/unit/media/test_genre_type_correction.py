"""题材类型纠正：纪录片/综艺/音乐演出归 TV，覆盖识别链两条路径。

识别有两条路：TMDB detail 走 `set_provider_data`，多源快照走
`_apply_snapshot_to_media`。早期纠正只加在前者，导致同一部纪录片在
目录同步场景（走快照）仍按 movie 归档 —— 纪录片与晚会就这样进了电影库，
还因为走错盘占了双份空间。

本模块锁定共用的 `correct_type_by_genres`，用生产快照的真实中文题材
（`["纪录"]`、`["音乐"]`）验证。
"""

from types import SimpleNamespace

import pytest

from app.domain.mediatypes import MediaType
from app.media.models import build_category_rule_map, correct_type_by_genres


def _rule_map():
    def ent(media_type, name, rules, is_default=0):
        return SimpleNamespace(media_type=media_type, name=name, rules=rules, is_default=is_default, enabled=1)

    return build_category_rule_map(
        [
            ent("movie", "华语电影", {"original_language": "zh,cn,bo,za"}),
            ent("movie", "动画电影", {"genre_ids": "16"}),
            ent("movie", "外语电影", {}, is_default=1),
            ent("tv", "动漫", {"genre_ids": "16"}),
            ent("tv", "纪录片", {"genre_ids": "99"}),
            ent("tv", "儿童", {"genre_ids": "10762"}),
            ent("tv", "综艺", {"genre_ids": "10764,10767,10402"}),
            ent("tv", "未分类", {}, is_default=1),
        ]
    )


RULE_MAP = _rule_map()


class TestNonFilmGenresBecomeTv:
    @pytest.mark.parametrize(
        ("case", "genres"),
        [
            # 生产快照的真实写法（中文）
            ("纯纪录片", ["纪录"]),
            ("纪录片（中文全称）", ["纪录片"]),
            ("音乐纪录片", ["音乐", "纪录"]),
            ("纯音乐会/晚会", ["音乐"]),
            # TMDB 原始写法（ID / 英文）
            ("Documentary by id", [{"id": 99, "name": "Documentary"}]),
            ("Music by id", [{"id": 10402, "name": "Music"}]),
            ("综艺 by id", [10764]),
            ("儿童", ["儿童"]),
        ],
    )
    def test_retypes_to_tv(self, case, genres):
        assert correct_type_by_genres(MediaType.MOVIE, genres, RULE_MAP) == MediaType.TV

    def test_documentary_wins_over_narrative_tag(self):
        # 纪录片常带「剧情」标签（历史重演/人物纪实），纪录片优先级更高
        assert correct_type_by_genres(MediaType.MOVIE, ["剧情", "纪录"], RULE_MAP) == MediaType.TV


class TestFilmStaysMovie:
    @pytest.mark.parametrize(
        ("case", "genres"),
        [
            # 音乐传记片：叙事题材保护
            ("剧情+音乐（音乐传记片）", ["剧情", "音乐"]),
            ("剧情+音乐+爱情", ["剧情", "音乐", "爱情"]),
            # 电影侧已有栏目
            ("动画电影", ["动画"]),
            ("动画纪录片", ["动画", "纪录"]),
            # 普通叙事片
            ("纯剧情片", ["剧情"]),
            ("动作片", ["动作"]),
            # 识别失败无题材，不靠类型逻辑兜底
            ("无题材信息 1", []),
            ("无题材信息 2", None),
        ],
    )
    def test_stays_movie(self, case, genres):
        assert correct_type_by_genres(MediaType.MOVIE, genres, RULE_MAP) == MediaType.MOVIE

    @pytest.mark.parametrize(
        "media_type",
        [MediaType.TV, MediaType.ANIME, MediaType.UNKNOWN, None],
    )
    def test_non_movie_untouched(self, media_type):
        # 非 movie 一律原样返回，避免把剧集/动漫降级
        assert correct_type_by_genres(media_type, ["纪录"], RULE_MAP) == media_type


class TestEmptyConfig:
    def test_no_tv_categories_still_uses_builtin_non_film_genres(self):
        # 配置里没有任何 TV 分类时，固有非电影题材仍然生效
        empty = build_category_rule_map([])
        assert correct_type_by_genres(MediaType.MOVIE, ["纪录"], empty) == MediaType.TV
        assert correct_type_by_genres(MediaType.MOVIE, ["音乐"], empty) == MediaType.TV


class TestBuildCategoryRuleMap:
    def test_default_category_rules_blanked(self):
        rm = build_category_rule_map(
            [SimpleNamespace(media_type="movie", name="外语电影", rules={"x": "1"}, is_default=1, enabled=1)]
        )
        # 默认分类是兜底，规则必须置空，否则会抢走其它分类
        assert rm["movie"]["外语电影"] == {}

    def test_disabled_category_excluded(self):
        rm = build_category_rule_map(
            [SimpleNamespace(media_type="tv", name="纪录片", rules={"genre_ids": "99"}, is_default=0, enabled=0)]
        )
        assert "纪录片" not in rm["tv"]
