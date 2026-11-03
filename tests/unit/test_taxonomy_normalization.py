"""taxonomy 归一化的边界场景：地区后缀、复合写法、未知值。

真实数据里 TMDB / 缓存 / 插件给出的值并不总是标准代码：
- `zh-CN` / `pt-BR` / `ja_JP` —— BCP 47 带地区
- `Japan (JP)` —— 名称+代码复合
早期 `language_codes`/`country_codes` 只做精确匹配，这些值一律返回空集，
而分类规则与身份构建都用它们判断语言/国家族 → 静默失效。
"""

import pytest

from app.media.category_taxonomy import load_taxonomy


class TestLanguageRegionSuffix:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("ja-JP", "ja"),
            ("ja_JP", "ja"),
            ("zh-CN", "zh"),
            ("zh-TW", "zh"),
            ("zh-Hans", "zh"),
            ("en-US", "en"),
            ("en-GB", "en"),
            ("pt-BR", "pt"),
            ("ko-KR", "ko"),
            ("fr-FR", "fr"),
            ("de-DE", "de"),
            ("th-TH", "th"),
        ],
    )
    def test_region_suffix_uses_primary_subtag(self, value, expected):
        assert load_taxonomy().language_codes(value) == {expected}

    def test_unknown_language_stays_empty(self):
        assert load_taxonomy().language_codes("xx-YY") == set()

    def test_empty_values(self):
        tax = load_taxonomy()
        assert tax.language_codes(None) == set()
        assert tax.language_codes("") == set()
        assert tax.language_codes([]) == set()


class TestCountryCompoundValues:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("JP", "JP"),
            ("Japan", "JP"),
            ("日本", "JP"),
            ("Japan (JP)", "JP"),
            ("United States (US)", "US"),
            ("South Korea (KR)", "KR"),
        ],
    )
    def test_country_compound_forms(self, value, expected):
        assert load_taxonomy().country_codes(value) == {expected}

    def test_unknown_country_stays_empty(self):
        assert load_taxonomy().country_codes("ZZ") == set()


class TestIdentityBuilderLanguageNormalization:
    """日语罗马音别名判定改用 taxonomy 归一化。"""

    @staticmethod
    def _is_ja(value):
        from app.media.category_taxonomy import load_taxonomy

        return "ja" in load_taxonomy().language_codes(value)

    @pytest.mark.parametrize("value", ["ja", "jp", "jpn", "日本語", "Japanese", "ja-JP"])
    def test_japanese_variants_recognized(self, value):
        assert self._is_ja(value) is True

    @pytest.mark.parametrize("value", ["en", "zh", "ko", "cn", None, ""])
    def test_non_japanese_not_recognized(self, value):
        assert self._is_ja(value) is False
