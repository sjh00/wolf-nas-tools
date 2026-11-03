"""新条目必须落在配置的布局里（分类结构），不能被平铺布局「截胡」。

真实故障：用户新增的《示例剧集》没有进「国产剧」目录，而是落到了
`/media/gof/medialink/TV/示例剧集 (2026)/Season 1`（平铺）。
当时 `CONFIG_MEDIA.TV_LAYOUT = category`、`TRANSFER_HISTORY.CATEGORY = 国产剧`
一切正常，问题在路径拼装：

    for media_path in self._layout_dirs(...):   # [分类路径, 平铺路径]
        ret_dir_path = season_dir               # 每轮直接覆盖
        if _exists(season_dir): ...
        if file_exist_flag: break               # 只有命中文件才提前退出

新入库的剧集目录与文件都不存在 → 循环跑完 → `ret_dir_path` 停在最后一个候选
（平铺）。于是分类布局只对库里已存在的条目生效；新条目一旦落错，后续集数
因为「平铺目录已存在」会一直跟随。
"""

import pytest

from app.domain.mediatypes import MediaType
from app.media.models import MediaInfo
from app.services.transfer.existence_checker import MediaExistenceChecker
from app.services.transfer.path_resolver import TransferPathResolver

EXT = ".mkv"


def _norm(path):
    return str(path or "").replace("\\", "/")


def _resolver(tv_flag=True, movie_flag=True):
    return TransferPathResolver(
        movie_path=["/media/movie"],
        tv_path=["/media/tv"],
        anime_path=["/media/anime"],
        movie_dir_rmt_format="{title} ({year})",
        movie_file_rmt_format="{title}",
        tv_dir_rmt_format="{title} ({year})",
        tv_season_rmt_format="Season {season}",
        tv_file_rmt_format="{title} - S{season:02d}E{episode:02d}",
        movie_category_flag=movie_flag,
        tv_category_flag=tv_flag,
        anime_category_flag=False,
    )


def _tv(episode=1, category="国产剧", title="示例剧集"):
    return MediaInfo(
        type=MediaType.TV,
        category=category,
        title=title,
        year="2026",
        begin_season=1,
        begin_episode=episode,
        end_episode=episode,
        org_string=f"{title}.S01E{episode:02d}.mkv",
        rev_string=f"{title}.S01E{episode:02d}.mkv",
    )


def _movie(category="华语电影", title="功夫"):
    return MediaInfo(
        type=MediaType.MOVIE,
        category=category,
        title=title,
        year="2004",
        org_string=f"{title}.2004.mkv",
        rev_string=f"{title}.2004.mkv",
    )


def _mk(path: str, name: str) -> None:
    """在真实文件系统上创建目录与文件（checker 用 os.path.exists 判断）。"""
    import os

    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, name), "w", encoding="utf-8") as fh:
        fh.write("x")


class TestNewTvLandsInCategoryLayout:
    def test_new_show_without_any_existing_path_uses_category_dir(self, tmp_path):
        """核心回归：全新剧集（目录与文件都不存在）必须落分类目录。"""
        root = str(tmp_path / "TV")
        checker = MediaExistenceChecker(_resolver(tv_flag=True))

        dir_exists, ret_dir, file_exists, ret_file = checker.is_media_exists(root, _tv())

        assert _norm(ret_dir) == f"{_norm(root)}/国产剧/示例剧集 (2026)/Season 1"
        assert dir_exists is False, "目录尚不存在，应有 makedirs 走到这一步"
        assert file_exists is False
        # 未命中已有文件时返回不带扩展名的目标基名，扩展名由 _do_transfer_file 追加
        assert _norm(ret_file) == f"{_norm(root)}/国产剧/示例剧集 (2026)/Season 1/示例剧集 - S01E01"

    def test_new_episode_follows_existing_category_dir(self, tmp_path):
        """已有剧集在分类目录里：新集数继续放分类目录。"""
        root = str(tmp_path / "TV")
        season_dir = tmp_path / "TV" / "国产剧" / "示例剧集 (2026)" / "Season 1"
        _mk(str(season_dir), "示例剧集 - S01E01.mkv")
        checker = MediaExistenceChecker(_resolver(tv_flag=True))

        dir_exists, ret_dir, _file_exists, _ret_file = checker.is_media_exists(root, _tv(episode=2))

        assert dir_exists is True
        assert _norm(ret_dir) == f"{_norm(root)}/国产剧/示例剧集 (2026)/Season 1"

    def test_existing_flat_copy_is_kept_to_avoid_duplicates(self, tmp_path):
        """历史平铺目录里已有该集：沿用平铺，不重复入库到分类目录。"""
        root = str(tmp_path / "TV")
        flat_season = tmp_path / "TV" / "示例剧集 (2026)" / "Season 1"
        _mk(str(flat_season), "示例剧集 - S01E01.mkv")
        checker = MediaExistenceChecker(_resolver(tv_flag=True))

        _dir_exists, ret_dir, file_exists, _ret_file = checker.is_media_exists(root, _tv(episode=1))

        assert file_exists is True
        assert _norm(ret_dir) == f"{_norm(root)}/示例剧集 (2026)/Season 1", "已存在的副本不应被搬到分类目录"

    def test_category_layout_disabled_uses_flat(self, tmp_path):
        """配置为平铺时，新剧集落平铺目录。"""
        root = str(tmp_path / "TV")
        checker = MediaExistenceChecker(_resolver(tv_flag=False))

        _dir_exists, ret_dir, _file_exists, _ret_file = checker.is_media_exists(root, _tv())

        assert _norm(ret_dir) == f"{_norm(root)}/示例剧集 (2026)/Season 1"

    def test_empty_category_falls_back_to_flat(self, tmp_path):
        """分类识别为空时只能平铺，不应拼出空目录名。"""
        root = str(tmp_path / "TV")
        checker = MediaExistenceChecker(_resolver(tv_flag=True))

        _dir_exists, ret_dir, _file_exists, _ret_file = checker.is_media_exists(root, _tv(category=""))

        assert _norm(ret_dir) == f"{_norm(root)}/示例剧集 (2026)/Season 1"


class TestNewMovieLandsInCategoryLayout:
    def test_new_movie_uses_category_dir_not_favorites(self, tmp_path):
        """新电影落分类目录；「精选」只在片已存在时沿用。"""
        root = str(tmp_path / "电影")
        checker = MediaExistenceChecker(_resolver(movie_flag=True))

        _dir_exists, ret_dir, file_exists, _ret_file = checker.is_media_exists(root, _movie())

        assert _norm(ret_dir) == f"{_norm(root)}/华语电影/功夫 (2004)"
        assert file_exists is False

    def test_movie_already_in_favorites_is_kept(self, tmp_path):
        root = str(tmp_path / "电影")
        fav = tmp_path / "电影" / "精选" / "功夫 (2004)"
        _mk(str(fav), "功夫.mkv")
        checker = MediaExistenceChecker(_resolver(movie_flag=True))

        _dir_exists, ret_dir, file_exists, _ret_file = checker.is_media_exists(root, _movie())

        assert file_exists is True
        assert _norm(ret_dir) == f"{_norm(root)}/精选/功夫 (2004)"

    def test_movie_layout_disabled_uses_flat(self, tmp_path):
        root = str(tmp_path / "电影")
        checker = MediaExistenceChecker(_resolver(movie_flag=False))

        _dir_exists, ret_dir, _file_exists, _ret_file = checker.is_media_exists(root, _movie())

        assert _norm(ret_dir) == f"{_norm(root)}/功夫 (2004)"


class TestPickTargetDir:
    """_pick_target_dir 的优先级：已有文件 > 已有目录 > 首选布局。"""

    @staticmethod
    def _fake_exists(paths):
        return lambda candidate: _norm(candidate) in {_norm(p) for p in paths}

    def test_prefers_dir_containing_file(self):
        exists = self._fake_exists(["/a/cat/x.mkv", "/a/x.mkv"])
        picked = MediaExistenceChecker._pick_target_dir(["/a/cat", "/a"], "/a/cat", "x", exists)
        assert _norm(picked) == "/a/cat"

    def test_falls_back_to_existing_dir(self):
        exists = self._fake_exists(["/a"])
        picked = MediaExistenceChecker._pick_target_dir(["/a/cat", "/a"], "/a/cat", "x", exists)
        assert _norm(picked) == "/a"

    def test_falls_back_to_preferred_when_nothing_exists(self):
        exists = self._fake_exists([])
        picked = MediaExistenceChecker._pick_target_dir(["/a/cat", "/a"], "/a/cat", "x", exists)
        assert _norm(picked) == "/a/cat", "都不存在时必须用首选布局，而不是最后一个候选"

    @pytest.mark.parametrize("file_name", ["", None])
    def test_without_file_name_only_checks_dirs(self, file_name):
        exists = self._fake_exists(["/a"])
        picked = MediaExistenceChecker._pick_target_dir(["/a/cat", "/a"], "/a/cat", file_name, exists)
        assert _norm(picked) == "/a"
