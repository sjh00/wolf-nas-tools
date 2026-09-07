"""MediaMigrateService / PathUtils.is_same_filesystem 单元测试."""

import os
from unittest.mock import MagicMock

import pytest

from app.services.media_migrate_service import MediaMigrateService
from app.utils.path_utils import PathUtils


class _Rec:
    def __init__(self, rid, tmdb, src_path, src_fn, dst_path, dst_fn, title="T", year="2020"):
        self.ID = rid
        self.TMDBID = tmdb
        self.SOURCE_PATH = src_path
        self.SOURCE_FILENAME = src_fn
        self.DEST_PATH = dst_path
        self.DEST_FILENAME = dst_fn
        self.TITLE = title
        self.YEAR = year


def _svc(records=None, download_repo=None):
    history = MagicMock()
    if records is not None:
        history.get_transfer_info_by.return_value = records
    return MediaMigrateService(
        history_manager=history,
        download_repo=download_repo or MagicMock(),
        downloader_core=None,
    )


class TestSameFilesystem:
    def test_same_dir(self, tmp_path):
        assert PathUtils.is_same_filesystem(str(tmp_path), str(tmp_path)) is True

    def test_same_parent(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        assert PathUtils.is_same_filesystem(str(a), str(b)) is True

    def test_none_returns_false(self):
        assert PathUtils.is_same_filesystem("", "/x") is False


class TestBuildTargetPath:
    def test_appends_basename(self, tmp_path):
        old = str(tmp_path / "Some.Movie")
        target = MediaMigrateService._build_target_path(str(tmp_path / "dest_root"), old)
        assert target == str(tmp_path / "dest_root" / "Some.Movie")

    def test_conflict_suffix(self, tmp_path):
        old = str(tmp_path / "Some.Movie")
        target_root = tmp_path / "dest_root"
        target_root.mkdir()
        (target_root / "Some.Movie").mkdir()  # 已存在同名目录
        target = MediaMigrateService._build_target_path(str(target_root), old)
        assert target == str(target_root / "Some.Movie.1")


class TestCollectDirs:
    def test_dedup(self, tmp_path):
        records = [
            _Rec(1, 100, "S1", "a.mkv", "D1", "a.mkv"),
            _Rec(2, 100, "S1", "b.mkv", "D2", "b.mkv"),
            _Rec(3, 100, "S2", "c.mkv", "D1", "c.mkv"),
        ]
        src, dst = MediaMigrateService._collect_dirs(records)
        assert src == {"S1", "S2"}
        assert dst == {"D1", "D2"}


class TestDetermineCross:
    def test_explicit_cross_override(self, tmp_path):
        svc = _svc()
        assert svc._determine_cross({str(tmp_path)}, {str(tmp_path)}, str(tmp_path / "x"), str(tmp_path / "y"), True) is True
        assert svc._determine_cross({str(tmp_path)}, {str(tmp_path)}, str(tmp_path / "x"), str(tmp_path / "y"), False) is False

    def test_auto_same_fs(self, tmp_path):
        svc = _svc()
        old = tmp_path / "old"
        old.mkdir()
        target = tmp_path / "new"
        target.mkdir()
        # 同一 tmp 分区 → 同盘
        assert svc._determine_cross({str(old)}, set(), str(target), str(target), None) is False


class TestMigrate:
    def test_same_drive_move(self, tmp_path):
        old_src = tmp_path / "bt" / "Movie.A"
        old_src.mkdir(parents=True)
        (old_src / "a.mkv").write_text("x")
        old_dst = tmp_path / "media" / "Movie.A"
        old_dst.mkdir(parents=True)
        (old_dst / "a.mkv").write_text("x")
        records = [
            _Rec(1, 100, str(old_src), "a.mkv", str(old_dst), "a.mkv"),
        ]
        target_source = tmp_path / "bt2"
        target_source.mkdir()
        target_dest = tmp_path / "media2"
        target_dest.mkdir()
        svc = _svc(records)

        result = svc.migrate(
            tmdb_id=100, target_source=str(target_source), target_dest=str(target_dest), cross_drive=False
        )

        assert result["cross_drive"] is False
        assert len(result["migrated_dirs"]) == 2
        # 源目录已移走，目标目录有新文件
        assert not (old_src / "a.mkv").exists()
        assert (target_source / "Movie.A" / "a.mkv").exists()
        assert (target_dest / "Movie.A" / "a.mkv").exists()
        # 更新了转移记录
        svc._history.update_transfer_paths.assert_called()

    def test_cross_drive_copy_then_remove(self, tmp_path):
        old_src = tmp_path / "bt" / "Movie.A"
        old_src.mkdir(parents=True)
        (old_src / "a.mkv").write_text("x")
        records = [
            _Rec(1, 100, str(old_src), "a.mkv", "", ""),
        ]
        target_source = tmp_path / "bt2"
        target_source.mkdir()
        target_dest = tmp_path / "media2"
        target_dest.mkdir()
        svc = _svc(records)

        result = svc.migrate(
            tmdb_id=100, target_source=str(target_source), target_dest=str(target_dest), cross_drive=True
        )

        assert result["cross_drive"] is True
        assert (target_source / "Movie.A" / "a.mkv").exists()
        assert not (old_src / "a.mkv").exists()  # 复制校验后删除旧


class _Torrent:
    def __init__(self, id, name, save_path, content_path):
        self.id = id
        self.name = name
        self.save_path = save_path
        self.content_path = content_path


def _svc_with_downloader(records, torrents=None, downloader_confs=None):
    history = MagicMock()
    history.get_transfer_info_by.return_value = records
    download_repo = MagicMock()
    downloader = MagicMock()
    downloader.get_downloader_conf.return_value = downloader_confs or {"qb": {"id": "qb", "name": "qb"}}
    downloader.get_torrents.return_value = torrents or []
    return MediaMigrateService(
        history_manager=history,
        download_repo=download_repo,
        downloader_core=downloader,
    )


class TestHasTorrentForSource:
    def test_content_path_exact_match(self):
        svc = _svc_with_downloader([])
        torrents = [{"id": "h", "name": "Movie.A", "save_path": "/bt", "content_path": "/bt/Movie.A/a.mkv"}]
        assert svc._has_torrent_for_source("/bt/Movie.A/a.mkv", "a.mkv", torrents) is True

    def test_content_path_multifile_dir(self):
        svc = _svc_with_downloader([])
        torrents = [{"id": "h", "name": "Movie.A", "save_path": "/bt", "content_path": "/bt/Movie.A"}]
        assert svc._has_torrent_for_source("/bt/Movie.A/a.mkv", "a.mkv", torrents) is True

    def test_no_match_is_orphan(self):
        svc = _svc_with_downloader([])
        torrents = [{"id": "h", "name": "Other.Movie", "save_path": "/bt2", "content_path": "/bt2/Other.Movie"}]
        assert svc._has_torrent_for_source("/bt/Movie.A/a.mkv", "a.mkv", torrents) is False

    def test_empty_torrents_is_orphan(self):
        svc = _svc_with_downloader([])
        assert svc._has_torrent_for_source("/bt/Movie.A/a.mkv", "a.mkv", []) is False


class TestDetectOrphans:
    def test_detects_orphan_when_no_torrent(self, tmp_path):
        old_src = tmp_path / "bt" / "Movie.A"
        old_src.mkdir(parents=True)
        (old_src / "a.mkv").write_text("x")
        records = [_Rec(1, 100, str(old_src), "a.mkv", str(tmp_path / "media" / "Movie.A"), "a.mkv")]
        svc = _svc_with_downloader(records, torrents=[])
        result = svc.detect_orphans(tmdb_id=100)
        assert result["total"] == 1
        assert result["orphans"][0]["source_filename"] == "a.mkv"

    def test_no_orphan_when_torrent_matches(self, tmp_path):
        old_src = tmp_path / "bt" / "Movie.A"
        old_src.mkdir(parents=True)
        (old_src / "a.mkv").write_text("x")
        records = [_Rec(1, 100, str(old_src), "a.mkv", str(tmp_path / "media" / "Movie.A"), "a.mkv")]
        torrents = [
            _Torrent(
                id="h",
                name="Movie.A",
                save_path=str(old_src),
                content_path=str(old_src / "a.mkv"),
            )
        ]
        svc = _svc_with_downloader(records, torrents=torrents)
        result = svc.detect_orphans(tmdb_id=100)
        assert result["total"] == 0

