"""分类匹配：空规则分类为“兜底”，不得吞掉后续精确分类。

回归：空规则的「华语电影」若排在「外语电影」之前，会导致外语片被归入华语目录。
"""

from app.media.category_matcher import get_category


def test_foreign_movie_falls_back_to_empty_last_category():
    rules = {
        "动画电影": {"genre_ids": "16"},
        "华语电影": {"original_language": "zh,cn,bo,za"},
        "外语电影": {},
    }
    assert get_category(rules, {"original_language": "en"}) == "外语电影"
    assert get_category(rules, {"original_language": "zh"}) == "华语电影"


def test_empty_category_before_specific_does_not_swallow():
    # 空规则兜底在前，也不能截断后续精确分类
    rules = {
        "华语电影": {},
        "外语电影": {"original_language": "en"},
    }
    assert get_category(rules, {"original_language": "en"}) == "外语电影"
    # 都不匹配时再落到兜底
    assert get_category(rules, {"original_language": "ja"}) == "华语电影"


def test_spider_man_english_not_matched_as_chinese_even_if_chinese_empty():
    # 空规则的华语排在动画之后、外语之前：英文片仍应命中外语
    rules = {
        "动画电影": {"genre_ids": "16"},
        "华语电影": {},
        "外语电影": {
            "original_language": "en,ko,ja,fr,de,es,it,ru",
            "origin_country": "US,JP,KR,GB,HK",
        },
    }
    info = {"genre_ids": [28, 12, 878], "original_language": "en", "origin_country": ["US"]}
    assert get_category(rules, info) == "外语电影"


def test_no_match_without_fallback_returns_empty():
    rules = {"华语电影": {"original_language": "zh"}}
    assert get_category(rules, {"original_language": "en"}) == ""


def test_only_empty_category_is_fallback():
    assert get_category({"未分类": {}}, {"original_language": "en"}) == "未分类"


def test_production_countries_dict_match():
    rules = {"华语电影": {"production_countries": "CN,TW,HK"}, "外语电影": {}}
    info = {"production_countries": [{"iso_3166_1": "TW"}, {"iso_3166_1": "US"}]}
    assert get_category(rules, info) == "华语电影"
