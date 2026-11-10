"""文件管理侧栏的库名区分。

多盘共用同一套目录结构（各盘都是 …/medialink/电影）时，侧栏会出现一排完全
相同的「电影」。只加一级父目录不够——父目录也叫 medialink，仍然无法区分。
"""

from app.services.media_file_service import disambiguate_library_names


def _paths(*paths):
    return [
        {"name": p.rstrip("/").split("/")[-1], "path": p.rstrip("/")} for p in paths
    ]


def _names(*paths):
    items = _paths(*paths)
    disambiguate_library_names(items)
    return [item["name"] for item in items]


class TestDisambiguation:
    def test_cross_disk_same_structure_gets_disk_prefix(self):
        """跨盘同名库要显示到能区分的层级，而不是三个一样的 medialink/电影."""
        assert _names(
            "/media/storedisk1/medialink/电影",
            "/media/favorites/medialink/电影",
            "/media/gof/medialink/电影",
        ) == [
            "storedisk1/medialink/电影",
            "favorites/medialink/电影",
            "gof/medialink/电影",
        ]

    def test_cross_disk_tv_same_structure(self):
        assert _names(
            "/media/storedisk2/medialink/TV",
            "/media/favorites/medialink/TV",
            "/media/gof/medialink/TV",
        ) == [
            "storedisk2/medialink/TV",
            "favorites/medialink/TV",
            "gof/medialink/TV",
        ]

    def test_unique_names_are_untouched(self):
        assert _names("/media/a/电影", "/media/b/TV", "/media/c/动漫") == [
            "电影",
            "TV",
            "动漫",
        ]

    def test_different_parent_needs_only_one_level(self):
        """父目录不同时一级就够，不必一直加深到盘名."""
        assert _names("/media/a/剧集/电影", "/media/a/电影/电影") == [
            "剧集/电影",
            "电影/电影",
        ]

    def test_mixed_unique_and_duplicate(self):
        assert _names(
            "/media/storedisk1/medialink/电影",
            "/media/gof/medialink/电影",
            "/media/storedisk2/medialink/TV",
        ) == [
            "storedisk1/medialink/电影",
            "gof/medialink/电影",
            "TV",
        ]

    def test_identical_relative_paths_fall_back_to_full_path(self):
        names = _names("/mnt/a/电影", "/mnt2/a/电影")

        assert len(set(names)) == 2, names

    def test_single_item_keeps_name(self):
        assert _names("/media/storedisk1/medialink/电影") == ["电影"]
