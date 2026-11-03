"""分类回归：国语片必须进「华语电影/国产剧」，不能掉到「外语电影」。

真实故障（用户反馈「国语片还是跑到外语电影里去了」）：

    [2790] 《丐世英雄》 cat=华语电影
           /media/favorites/medialink/电影/外语电影/丐世英雄 (1992)

`CATEGORY` 字段算对了（华语电影），但落盘路径用的是另一个值（外语电影）。
两处取值分叉的根因是 `_category_from_snapshot` 构造的分类输入缺了
`original_language` —— 而「华语电影」规则正是 `original_language = zh,cn,bo,za`：

    info = {genres, countries, spoken_languages, tags, content_profile, providers}
                                                      ↑ 少了 original_language

规则匹配不上 → 一路掉到 `is_default` 的「外语电影」。快照里的
`spoken_languages` 是「普通话 / 广州话 / 廣州話」这类中文名，而规则值是语言代码，
taxonomy 又只登记了「汉语 / 中文 / Chinese / zh / cn」，无法兜底。
"""

import pytest

from app.media.category_matcher import get_category

# 线上数据 CONFIG_CATEGORY_RULE（按 SORT_ORDER：华语1 → 动画2 → 外语3 default）
MOVIE_RULES = {
    "华语电影": {"original_language": "zh,cn,bo,za"},
    "动画电影": {"genre_ids": "16"},
    "外语电影": {},
}
TV_RULES = {
    "动漫": {"genre_ids": "16"},
    "纪录片": {"genre_ids": "99"},
    "国产剧": {"origin_country": "CN,TW,HK"},
    "欧美剧": {"origin_country": "US,FR,GB,DE,ES,IT,NL,PT,RU,UK"},
    "日韩剧": {"origin_country": "JP,KP,KR,TH,IN,SG"},
    "未分类": {},
}


class TestChineseMovieStaysChinese:
    @pytest.mark.parametrize(
        ("label", "info"),
        [
            ("original_language=cn", {"original_language": "cn"}),
            ("original_language=zh", {"original_language": "zh"}),
            ("仅有 普通话 spoken_languages", {"spoken_languages": ["普通话"]}),
            ("仅有 国语", {"spoken_languages": ["国语"]}),
            ("仅有 汉语", {"spoken_languages": ["汉语"]}),
            ("粤语片", {"original_language": "cn", "spoken_languages": ["广州话 / 廣州話"]}),
            ("粤语（简写）", {"spoken_languages": ["粤语"]}),
            ("台语片", {"spoken_languages": ["台語"]}),
            ("中英合拍（original=cn）", {"original_language": "cn", "spoken_languages": ["普通话", "English"]}),
        ],
    )
    def test_chinese_movie_not_foreign(self, label, info):
        assert get_category(MOVIE_RULES, info, "movie") == "华语电影", f"{label} 被误判为外语片"

    def test_chinese_animation_prefers_chinese_over_animation(self):
        """华语动画：华语排序在前，应判华语电影（而非动画电影）。"""
        assert get_category(MOVIE_RULES, {"original_language": "cn", "genres": [16]}, "movie") == "华语电影"


class TestForeignMovieNotMisclassified:
    @pytest.mark.parametrize(
        ("label", "info"),
        [
            ("英语片", {"original_language": "en", "spoken_languages": ["English"], "countries": ["US"]}),
            ("日语片", {"original_language": "ja", "spoken_languages": ["日语"]}),
            ("韩语片", {"original_language": "ko", "spoken_languages": ["韩语"]}),
            ("法语片", {"original_language": "fr", "spoken_languages": ["法语"]}),
            ("无语言信息", {"genres": [35]}),
        ],
    )
    def test_foreign_stays_foreign(self, label, info):
        assert get_category(MOVIE_RULES, info, "movie") == "外语电影", f"{label} 被误判"

    def test_foreign_animation_is_animation(self):
        assert get_category(MOVIE_RULES, {"original_language": "en", "genres": [16]}, "movie") == "动画电影"


class TestSnapshotFieldExtraction:
    """`_snapshot_field_value` 要能从 FieldValue 包装里取值。"""

    def test_reads_field_value_wrapper(self):
        from app.services.transfer.filetransfer_service import _snapshot_field_value

        class _FV:
            value = "cn"

        class _Snap:
            fields = {"original_language": _FV()}

        assert _snapshot_field_value(_Snap(), "original_language") == "cn"

    def test_reads_plain_value(self):
        from app.services.transfer.filetransfer_service import _snapshot_field_value

        class _Snap:
            fields = {"original_language": "cn"}

        assert _snapshot_field_value(_Snap(), "original_language") == "cn"

    def test_missing_field_returns_none(self):
        from app.services.transfer.filetransfer_service import _snapshot_field_value

        class _Snap:
            fields = {}

        assert _snapshot_field_value(_Snap(), "original_language") is None

    def test_snapshot_without_fields_attr(self):
        from app.services.transfer.filetransfer_service import _snapshot_field_value

        class _Snap:
            pass

        assert _snapshot_field_value(_Snap(), "original_language") is None
