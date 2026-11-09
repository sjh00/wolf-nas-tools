"""回归测试：上游社区译名被灌入推广广告时的清洗。

现象：刮削器返回带成人站地址的影视标题（如「某片网：4488569.com 片名」），
该文案来自 TMDB 社区贡献的中文译名，被原样写入目录名/NFO。
广告域名常用 Unicode 数学数字（𝟲/𝟵）与全角冒号伪装，规避常规裸域名规则。
"""

from app.domain.media_types import ProviderMediaType
from app.domain.validators.media_title import (
    clean_advertisement_title,
    is_advertisement_title,
    is_valid_media_title,
    sanitize_title,
)
from app.media.lookup.tmdb_client import get_tmdb_chinese_title, update_tmdbinfo_cn_title
from app.media.parser._metainfo import meta_info

# 线上数据中实际出现的污染标题
_POLLUTED = [
    "看操姦片网：44885𝟲9.com  镖人：风起大漠",
    "看操姦片网：44885𝟲9.com  刺杀小说家",
]
# 整条都是广告（清洗后无剩余内容）
_PURE_AD = "淫片网 448832𝟵.com  黄漫片网 448856𝟵.com"
# 正常标题必须零误伤（含"带 .com 的合法片名"与含站名关键字的正常长片名）
_CLEAN = [
    "镖人：风起大漠",
    "刺杀小说家",
    "独行月球",
    "Alibi.com",
    "Alibi.com 2",
    "1917",
    "十二怒汉",
    "Blades of the Guardians",
    "蜘蛛侠：英雄无归",
    "The 100",
    "2001 A Space Odyssey",
    "千与千寻",
    "色情男女",
]

class TestIsAdvertisementTitle:
    def test_detects_polluted_titles(self):
        for name in _POLLUTED:
            assert is_advertisement_title(name) is True, name

    def test_detects_pure_ad(self):
        assert is_advertisement_title(_PURE_AD) is True

    def test_clean_titles_not_flagged(self):
        for name in _CLEAN:
            assert is_advertisement_title(name) is False, name

    def test_empty_input(self):
        assert is_advertisement_title(None) is False
        assert is_advertisement_title("") is False

    def test_unicode_math_digits_do_not_bypass(self):
        """𝟲/𝟵 等数学数字必须与 ASCII 数字同等识别"""
        assert is_advertisement_title("测试站 4488569.com") is True
        assert is_advertisement_title("测试站 44885𝟲9.com") is True

    def test_site_word_alone_is_not_ad(self):
        """仅含站名关键词、无域名时不得误判（如《色情男女》）"""
        for name in ("色情男女", "淫片", "黄漫"):
            assert is_advertisement_title(name) is False, name

class TestCleanAdvertisementTitle:
    def test_strips_ad_keeps_real_title(self):
        assert clean_advertisement_title(_POLLUTED[0]) == "镖人：风起大漠"
        assert clean_advertisement_title(_POLLUTED[1]) == "刺杀小说家"

    def test_pure_ad_yields_empty(self):
        assert clean_advertisement_title(_PURE_AD) == ""

    def test_site_word_with_plain_domain_removed(self):
        """站名 + 普通域名同样清除，不留「某某」这类残渣"""
        assert clean_advertisement_title("某某片网 evil.com") == ""

    def test_ad_prefix_before_real_title(self):
        assert clean_advertisement_title("某某片网 123456.com 独行月球") == "独行月球"

    def test_clean_titles_untouched(self):
        for name in _CLEAN:
            assert clean_advertisement_title(name) == name, name

class TestSanitizeTitle:
    def test_falls_back_when_fully_ad(self):
        assert sanitize_title(_PURE_AD, "Moon Man") == "Moon Man"

    def test_keeps_cleaned_when_has_title(self):
        assert sanitize_title(_POLLUTED[1], "A Writer's Odyssey") == "刺杀小说家"

    def test_none_uses_fallback(self):
        assert sanitize_title(None, "Moon Man") == "Moon Man"

class TestValidMediaTitleUnaffected:
    def test_clean_titles_still_valid(self):
        for name in _CLEAN:
            assert is_valid_media_title(name) is True, name

class TestTmdbCnTitleRejectsAd:
    def test_polluted_translation_skipped(self):
        """被灌入广告的 zh-CN 译名不得被采纳"""
        info = {
            "media_type": ProviderMediaType.MOVIE,
            "title": "Moon Man",
            "original_title": "Moon Man",
            "alternative_titles": {"titles": []},
            "translations": {
                "translations": [
                    {"iso_639_1": "zh-CN", "data": {"title": _PURE_AD}},
                ]
            },
        }
        assert get_tmdb_chinese_title(info) != _PURE_AD

    def test_polluted_translation_falls_back_to_clean_one(self):
        """多个中文译名时，跳过广告条目取正常的"""
        info = {
            "media_type": ProviderMediaType.MOVIE,
            "title": "Moon Man",
            "alternative_titles": {"titles": []},
            "translations": {
                "translations": [
                    {"iso_639_1": "zh-HK", "data": {"title": _PURE_AD}},
                    {"iso_639_1": "zh-TW", "data": {"title": "独行月球"}},
                ]
            },
        }
        assert get_tmdb_chinese_title(info) == "独行月球"

    def test_polluted_alternative_title_skipped(self):
        info = {
            "media_type": ProviderMediaType.MOVIE,
            "title": "Moon Man",
            "alternative_titles": {"titles": [{"title": _PURE_AD, "iso_3166_1": "CN"}]},
            "translations": {"translations": []},
        }
        assert get_tmdb_chinese_title(info) != _PURE_AD

    def test_update_sanitizes_already_chinese_polluted_title(self):
        """title 本身已是（被污染的）中文时，补全分支原本不会进入，仍需兜底清洗"""
        info = {
            "media_type": ProviderMediaType.MOVIE,
            "title": _PURE_AD,
            "original_title": "Moon Man",
            "alternative_titles": {"titles": []},
            "translations": {"translations": []},
        }
        result = update_tmdbinfo_cn_title(info, "zh")
        assert not is_advertisement_title(result["title"])
        assert result["title"] == "Moon Man"

    def test_update_keeps_clean_title(self):
        info = {
            "media_type": ProviderMediaType.MOVIE,
            "title": "独行月球",
            "original_title": "Moon Man",
            "alternative_titles": {"titles": []},
            "translations": {"translations": []},
        }
        assert update_tmdbinfo_cn_title(info, "zh")["title"] == "独行月球"

class TestMetaInfoStripsAd:
    """存量库里已被污染的目录名再次刮削时，也要能还原出正确片名"""

    def test_polluted_filename_resolves_chinese_title(self):
        mi = meta_info("看操姦片网：44885𝟲9.com  刺杀小说家 (2021) - 2160p.mp4")
        assert mi.cn_name == "刺杀小说家"

    def test_polluted_filename_resolves_second_sample(self):
        mi = meta_info("看操姦片网：44885𝟲9.com  镖人：风起大漠 (2026) - 1080p.mkv")
        assert mi.cn_name == "镖人：风起大漠"

    def test_pure_ad_filename_yields_no_name(self):
        """整条是广告时宁可不识别，也不能把广告写进目录名"""
        mi = meta_info("淫片网 448832𝟵.com  黄漫片网 448856𝟵.com (2022) - 2160p.mp4")
        assert mi.cn_name is None
        assert not is_advertisement_title(mi.get_name())

    def test_legit_dotcom_title_still_parses(self):
        """《Alibi.com》这类合法 .com 片名不得被广告规则误伤"""
        mi = meta_info("Alibi.com.2.2023.1080p.BluRay.x264-GROUP.mkv")
        assert not is_advertisement_title(mi.get_name())
