"""默认分类模板必须让「音乐」有归属。

晚会 / 演唱会 / 音乐节在 TMDB 里是 movie 类型、题材 10402(音乐)。
若「综艺」不接音乐题材，这些内容会掉进电影的默认分类「外语电影」，
既进不了 TV 目录，也会因为走电影路径而跨盘。

音乐传记片（剧情+音乐）不受影响：题材判定阶段带叙事题材的作品
仍留在电影侧，分类匹配只在同类型内进行。
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("ruamel.yaml")

TEMPLATE = Path(__file__).resolve().parents[3] / "config" / "default-category.yaml"


@pytest.fixture(scope="module")
def template():
    with open(TEMPLATE, encoding="utf-8") as f:
        return yaml.YAML().load(f) or {}


def _genre_ids(rules) -> set[str]:
    if not isinstance(rules, dict):
        return set()
    raw = rules.get("genre_ids")
    if raw in (None, ""):
        return set()
    return {part.strip() for part in str(raw).split(",") if part.strip()}


class TestTvMusicGenre:
    def test_variety_accepts_music(self, template):
        tv = template.get("tv") or {}
        assert "10402" in _genre_ids(tv.get("综艺")), "综艺分类需包含音乐(10402)"

    def test_variety_keeps_existing_genres(self, template):
        tv = template.get("tv") or {}
        ids = _genre_ids(tv.get("综艺"))
        # 不能为了加音乐丢掉原有综艺题材
        assert {"10764", "10767"} <= ids

    def test_documentary_still_configured(self, template):
        tv = template.get("tv") or {}
        assert "99" in _genre_ids(tv.get("纪录片"))

    def test_music_not_in_movie_categories(self, template):
        """音乐不能出现在电影侧分类，否则音乐会会被电影分类抢走。"""
        for name, rules in (template.get("movie") or {}).items():
            assert "10402" not in _genre_ids(rules), f"电影分类「{name}」不应匹配音乐题材"
