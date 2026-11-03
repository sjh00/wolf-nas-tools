"""题材只在 TV 侧有分类时，按 TV 归档。

媒体库的分类配置里，「纪录片」「综艺」「儿童」通常只挂在 TV 侧
（CONFIG_CATEGORY.MEDIA_TYPE='tv'），电影侧只有按语言（华语电影）或
动画（动画电影）划分的分类。

一部纪录片在 TMDB 里是 movie。照 movie 归档的后果是：
- 只能落进电影默认分类（外语电影），无法进入 TV/纪录片
- TV/纪录片 目录永远收不到新内容
- 送错类型还会走到另一块盘的媒体库目录，跨盘后无法硬链接

因此：题材键只在 TV 侧出现时，把类型纠正为 TV。该判断完全由分类配置驱动，
不硬编码 genre 编号 —— 用户改分类规则后行为随之变化。
"""

import pytest

from app.media.models import MediaInfo, _genre_keys_from_rules, _tv_only_genre_keys

# 线上真实规则结构（CONFIG_CATEGORY + CONFIG_CATEGORY_RULE 导出）
RULE_MAP = {
    "anime": {"动漫": {"genre_ids": "16"}},
    "movie": {
        "华语电影": {"original_language": "zh,cn,bo,za"},
        "动画电影": {"genre_ids": "16"},
        "外语电影": {},
    },
    "tv": {
        "动漫": {"genre_ids": "16"},
        "纪录片": {"genre_ids": "99"},
        "儿童": {"genre_ids": "10762"},
        "综艺": {"genre_ids": "10764,10767"},
        "国产剧": {"origin_country": "CN,TW,HK"},
        "未分类": {},
    },
}


class TestGenreKeysFromRules:
    def test_comma_separated_string_is_split(self):
        # 早期实现把 "10764,10767" 整串当一个名称查，结果为空集，
        # 综艺题材因此从未被识别为 TV-only
        assert _genre_keys_from_rules({"genre_ids": "10764,10767"}) == {"reality", "talk"}

    def test_single_id(self):
        assert _genre_keys_from_rules({"genre_ids": "99"}) == {"documentary"}

    def test_list_input(self):
        assert _genre_keys_from_rules({"genres": [99, 10762]}) == {"documentary", "kids"}

    def test_non_genre_rule_yields_nothing(self):
        assert _genre_keys_from_rules({"origin_country": "CN,TW,HK"}) == set()

    def test_empty_and_none(self):
        assert _genre_keys_from_rules({}) == set()
        assert _genre_keys_from_rules(None) == set()


class TestTvOnlyGenreKeys:
    def test_computes_difference_from_config(self):
        # 固有非电影题材始终并入，配置里只在 TV 侧出现的也并入
        assert _tv_only_genre_keys(RULE_MAP) == {
            "documentary",
            "kids",
            "reality",
            "talk",
            "music",
            "news",
            "soap",
            "sport",
        }

    def test_genre_with_movie_home_is_excluded(self):
        # 动画(16) 在电影侧有「动画电影」，不算 TV-only
        assert "animation" not in _tv_only_genre_keys(RULE_MAP)

    def test_non_film_genres_present_even_without_config(self):
        # 配置里完全没有任何分类时，「音乐」「纪录片」等固有非电影题材仍然归 TV
        empty = _tv_only_genre_keys({"movie": {}, "tv": {}})
        assert {"documentary", "music", "reality", "talk", "kids"} <= empty

    def test_empty_config(self):
        # 无配置时仅剩固有非电影题材
        assert _tv_only_genre_keys({"movie": {}, "tv": {}}) == {
            "documentary",
            "kids",
            "music",
            "news",
            "reality",
            "soap",
            "sport",
            "talk",
        }


class TestTypeCorrection:
    @staticmethod
    def _resolve(genres, media_type="movie"):
        info = MediaInfo()
        info.type = None
        rule_map = RULE_MAP
        hint = "tv" if media_type == "movie" and info._has_tv_only_genre({"genres": genres}, rule_map) else media_type
        return hint

    @pytest.mark.parametrize(
        ("genres", "expected"),
        [
            ([{"id": 99, "name": "Documentary"}], "tv"),
            ([{"id": 10767, "name": "Talk Show"}], "tv"),
            ([{"id": 10764, "name": "Reality"}], "tv"),
            ([{"id": 10762, "name": "Kids"}], "tv"),
            # 音乐会/演唱会/晚会：纯音乐题材，不是电影
            ([{"id": 10402, "name": "Music"}], "tv"),
            # 纪录片带剧情标签（历史重演/人物纪实）仍归 TV —— 纪录片优先
            ([{"id": 18, "name": "Drama"}, {"id": 99, "name": "Documentary"}], "tv"),
            # 音乐 + 纪录片（音乐会实况纪录片）
            ([{"id": 10402, "name": "Music"}, {"id": 99, "name": "Documentary"}], "tv"),
        ],
    )
    def test_non_film_genres_become_tv(self, genres, expected):
        assert self._resolve(genres) == expected

    @pytest.mark.parametrize(
        "genres",
        [
            [{"id": 18, "name": "Drama"}],
            [{"id": 28, "name": "Action"}],
            [{"id": 16, "name": "Animation"}],  # 有「动画电影」分类，保持电影
            [{"id": 18, "name": "Drama"}, {"id": 16, "name": "Animation"}],
            # 音乐传记片/歌舞片：带剧情/爱情等叙事题材，必须留在电影侧
            ([{"id": 18, "name": "Drama"}, {"id": 10402, "name": "Music"}]),
            (
                [
                    {"id": 18, "name": "Drama"},
                    {"id": 10402, "name": "Music"},
                    {"id": 10749, "name": "Romance"},
                ]
            ),
        ],
    )
    def test_narrative_films_stay_movie(self, genres):
        assert self._resolve(genres) == "movie"

    def test_animation_plus_documentary_prefers_movie(self):
        # 动画纪录片：动画在电影侧有分类，不该强行改判
        genres = [{"id": 16, "name": "Animation"}, {"id": 99, "name": "Documentary"}]
        assert self._resolve(genres) == "movie"

    def test_no_genres_keeps_movie(self):
        assert self._resolve([]) == "movie"

    def test_mixed_genre_with_tv_only_still_retypes(self):
        # 剧情 + 纪录片：纪录片只在 TV 侧有分类，仍应归档到 TV
        genres = [{"id": 18, "name": "Drama"}, {"id": 99, "name": "Documentary"}]
        assert self._resolve(genres) == "tv"


class TestSetProviderDataEndToEnd:
    """走真实 set_provider_data 路径（分类配置用固定的规则替身，不依赖本地 DB）。"""

    @staticmethod
    def _install_rules(monkeypatch):
        from types import SimpleNamespace

        import app.media.models as models_mod

        entities = []
        for mtype, name, rules, is_default in [
            ("movie", "华语电影", {"original_language": "zh,cn,bo,za"}, 0),
            ("movie", "动画电影", {"genre_ids": "16"}, 0),
            ("movie", "外语电影", {}, 1),
            ("tv", "纪录片", {"genre_ids": "99"}, 0),
            ("tv", "综艺", {"genre_ids": "10764,10767"}, 0),
            ("tv", "未分类", {}, 1),
        ]:
            entities.append(
                SimpleNamespace(media_type=mtype, name=name, rules=rules, is_default=is_default, enabled=True)
            )

        class _FakeAdapter:
            def __init__(self, *a, **kw):
                pass

            def get_all(self):
                return entities

        monkeypatch.setattr(models_mod, "CategoryConfigRepositoryAdapter", _FakeAdapter)

    def test_documentary_movie_becomes_tv(self, monkeypatch):
        from app.domain.mediatypes import MediaType

        self._install_rules(monkeypatch)
        info = MediaInfo()
        info.set_provider_data(
            {
                "id": 123456,
                "media_type": "movie",
                "title": "第四公民",
                "genres": [{"id": 99, "name": "Documentary"}],
                "production_countries": [{"iso_3166_1": "US"}],
            }
        )
        assert info.type == MediaType.TV

    def test_normal_movie_stays_movie(self, monkeypatch):
        from app.domain.mediatypes import MediaType

        self._install_rules(monkeypatch)
        info = MediaInfo()
        info.set_provider_data(
            {
                "id": 654321,
                "media_type": "movie",
                "title": "看不见的顶峰",
                "genres": [{"id": 18, "name": "Drama"}],
                "production_countries": [{"iso_3166_1": "CN"}],
            }
        )
        assert info.type == MediaType.MOVIE

    def test_animated_documentary_stays_movie(self, monkeypatch):
        from app.domain.mediatypes import MediaType

        self._install_rules(monkeypatch)
        info = MediaInfo()
        info.set_provider_data(
            {
                "id": 777777,
                "media_type": "movie",
                "title": "Flee",
                "genres": [{"id": 16, "name": "Animation"}, {"id": 99, "name": "Documentary"}],
            }
        )
        assert info.type == MediaType.MOVIE
