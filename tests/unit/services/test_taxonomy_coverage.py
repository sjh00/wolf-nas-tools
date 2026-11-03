"""taxonomy 覆盖率回归：真实快照里出现的语言/国家/类型值必须都能识别。

背景：分类规则用 `origin_country` / `original_language` / `genre_ids` 匹配，
而 taxonomy 负责把「人类可读名」归一化成内部代码：

- 规则值是代码（`JP,KP,KR,TH,IN,SG`）
- 实际值也是代码（countries）或**本地名**（spoken_languages: 普通话/Français/한국어）

taxonomy 缺项时 `country_codes`/`language_codes` 返回空 → 该规则永远匹配不上
→ 条目掉到 `is_default` 的分类。曾导致：
- `SG`（新加坡）/`KP`（朝鲜）缺失 → 新加坡、朝鲜剧全部进「未分类」
- `한국어/조선말`（韩语）、`Français`、`Deutsch` 等本地名缺失 → 语言维度失效

本测试用生产快照实测到的值做断言，防止再次漏项。
"""

import pytest

from app.media.category_matcher import get_category
from app.media.category_taxonomy import load_taxonomy

# 线上数据 CONFIG_CATEGORY_RULE（tv 按 SORT_ORDER）
TV_RULES = {
    "动漫": {"genre_ids": "16"},
    "纪录片": {"genre_ids": "99"},
    "儿童": {"genre_ids": "10762"},
    "综艺": {"genre_ids": "10764,10767"},
    "国产剧": {"origin_country": "CN,TW,HK"},
    "欧美剧": {"origin_country": "US,FR,GB,DE,ES,IT,NL,PT,RU,UK"},
    "日韩剧": {"origin_country": "JP,KP,KR,TH,IN,SG"},
    "未分类": {},
}
MOVIE_RULES = {
    "华语电影": {"original_language": "zh,cn,bo,za"},
    "动画电影": {"genre_ids": "16"},
    "外语电影": {},
}


class TestCountryCodes:
    @pytest.mark.parametrize("code", ["JP", "KP", "KR", "TH", "IN", "SG"])
    def test_asia_country_codes_resolve(self, code):
        """日韩剧规则里的每个国家码都必须能解析（曾缺 KP/SG）。"""
        assert load_taxonomy().country_codes(code) == {code}

    @pytest.mark.parametrize("code", ["CN", "TW", "HK", "US", "GB", "FR", "DE", "NL", "RU"])
    def test_other_rule_country_codes_resolve(self, code):
        assert load_taxonomy().country_codes(code) == {code}

    def test_country_names_and_codes_agree(self):
        """国家名与代码映射到同一个值。"""
        tax = load_taxonomy()
        assert tax.country_codes("新加坡") == {"SG"}
        assert tax.country_codes("Singapore") == {"SG"}
        assert tax.country_codes("朝鲜") == {"KP"}
        assert tax.country_codes("中国大陆") == {"CN"}


class TestLanguageCodes:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            # 中文族（含方言）
            ("zh", "zh"),
            ("cn", "zh"),
            ("普通话", "zh"),
            ("国语", "zh"),
            ("粤语", "zh"),
            ("广州话 / 廣州話", "zh"),
            ("台語", "zh"),
            ("Mandarin", "zh"),
            ("Cantonese", "zh"),
            # 其他语言的本地名（TMDB spoken_languages 就是这些写法）
            ("한국어/조선말", "ko"),
            ("Français", "fr"),
            ("Deutsch", "de"),
            ("Español", "es"),
            ("Italiano", "it"),
            ("Português", "pt"),
            ("日本語", "ja"),
            ("ภาษาไทย", "th"),
            ("हिन्दी", "hi"),
            ("العربية", "ar"),
            ("Русский", "ru"),
            ("Nederlands", "nl"),
            ("svenska", "sv"),
            ("Dansk", "da"),
            ("Český", "cs"),
            ("Bahasa indonesia", "id"),
        ],
    )
    def test_language_values_resolve(self, value, expected):
        assert load_taxonomy().language_codes(value) == {expected}


class TestTvClassificationEndToEnd:
    @pytest.mark.parametrize(
        ("label", "countries", "expected"),
        [
            ("新加坡剧", ["SG"], "日韩剧"),
            ("朝鲜剧", ["KP"], "日韩剧"),
            ("韩国剧", ["KR"], "日韩剧"),
            ("日本剧", ["JP"], "日韩剧"),
            ("泰国剧", ["TH"], "日韩剧"),
            ("印度剧", ["IN"], "日韩剧"),
            ("国产剧", ["CN"], "国产剧"),
            ("港剧", ["HK"], "国产剧"),
            ("台剧", ["TW"], "国产剧"),
            ("美剧", ["US"], "欧美剧"),
            ("英剧", ["GB"], "欧美剧"),
            ("荷兰剧", ["NL"], "欧美剧"),
            ("俄罗斯剧", ["RU"], "欧美剧"),
        ],
    )
    def test_tv_origin_country_routing(self, label, countries, expected):
        assert get_category(TV_RULES, {"countries": countries}, "tv") == expected

    def test_unknown_country_falls_back_to_default(self):
        assert get_category(TV_RULES, {"countries": ["ZZ"]}, "tv") == "未分类"


class TestMovieClassificationUnaffected:
    """补齐 taxonomy 后，原有的华语/外语判定不得回退。"""

    @pytest.mark.parametrize(
        ("info", "expected"),
        [
            ({"original_language": "cn"}, "华语电影"),
            ({"original_language": "zh"}, "华语电影"),
            ({"spoken_languages": ["普通话"]}, "华语电影"),
            ({"spoken_languages": ["粤语"]}, "华语电影"),
            ({"original_language": "en"}, "外语电影"),
            ({"original_language": "fr"}, "外语电影"),
            ({"original_language": "ko"}, "外语电影"),
            ({"spoken_languages": ["Français"]}, "外语电影"),
            ({"spoken_languages": ["한국어/조선말"]}, "外语电影"),
        ],
    )
    def test_movie_language_routing(self, info, expected):
        assert get_category(MOVIE_RULES, info, "movie") == expected
