"""默认分类模板的国家覆盖：漏一个国家就掉「未分类」。

生产实测：部分加拿大出品剧集的 origin_country 只有 CA，
而「欧美剧」规则缺 CA → 落进「未分类」，与记录里的 CATEGORY=欧美剧 不一致。

这类漏配很难在运行期看出来（只是静静掉进兜底分类），因此用模板断言守住。
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("ruamel.yaml")

TEMPLATE = Path(__file__).resolve().parents[3] / "config" / "default-category.yaml"


@pytest.fixture(scope="module")
def tv_rules():
    with open(TEMPLATE, encoding="utf-8") as f:
        data = yaml.YAML().load(f) or {}
    return data.get("tv") or {}


def _codes(rules) -> set[str]:
    if not isinstance(rules, dict):
        return set()
    raw = rules.get("origin_country")
    if raw in (None, ""):
        return set()
    return {part.strip().upper() for part in str(raw).split(",") if part.strip()}


class TestWesternCoverage:
    @pytest.mark.parametrize(
        "code",
        [
            "US",  # 美国
            "CA",  # 加拿大（部分剧集唯一的 origin_country）
            "GB", "UK",  # 英国
            "FR", "DE", "ES", "IT",  # 西欧/南欧
            "NL", "PT", "RU",  # 其它
        ],
    )
    def test_western_countries_covered(self, tv_rules, code):
        assert code in _codes(tv_rules.get("欧美剧")), f"欧美剧规则缺 {code}"

    def test_canada_not_falling_to_unclassified(self, tv_rules):
        """加拿大剧必须能匹配欧美剧，而不是掉进兜底分类。"""
        western = _codes(tv_rules.get("欧美剧"))
        asian = _codes(tv_rules.get("日韩剧"))
        # CA 只能出现在欧美剧侧
        assert "CA" in western
        assert "CA" not in asian


class TestAsianCoverage:
    @pytest.mark.parametrize(
        "code",
        ["CN", "TW", "HK"],  # 国产剧
    )
    def test_chinese_regions(self, tv_rules, code):
        assert code in _codes(tv_rules.get("国产剧"))

    @pytest.mark.parametrize(
        "code",
        ["JP", "KR", "KP", "TH", "IN", "SG"],
    )
    def test_asian_countries(self, tv_rules, code):
        assert code in _codes(tv_rules.get("日韩剧"))


class TestNoOverlap:
    def test_chinese_regions_not_in_other_groups(self, tv_rules):
        cn = _codes(tv_rules.get("国产剧"))
        western = _codes(tv_rules.get("欧美剧"))
        asian = _codes(tv_rules.get("日韩剧"))
        # 国产剧优先匹配，但不能与其他组重叠导致歧义
        assert not (cn & western)
        assert not (cn & asian)
