"""多版本/重复文件识别单元测试.

验证 TransferRepository.get_multi_version_groups 与 FileIndexService.get_versions / list_duplicates：
- 同一 tmdb_id 下多个不同文件 → 视为多版本
- 同一目录内多个不同文件也算多版本（正片+花絮/不同规格）
- 单文件作品不视为多版本
"""

from contextlib import contextmanager

from app.db.models import TRANSFERHISTORY
from app.db.repositories.transfer_repository import TransferRepository
from app.services.file_index_service import FileIndexService


class _TestableTransferRepository(TransferRepository):
    """测试用 Repo：把 session 替换为 db_session，避免连全局 Database。"""

    def __init__(self, session):
        self._test_session = session
        super().__init__()

    @contextmanager
    def session(self):
        yield self._test_session


def _mk(tmdb, dest_path, dest_fn, title, year, se="S01"):
    return dict(
        MODE="link",
        TYPE="MOVIE",
        CATEGORY="",
        TMDBID=tmdb,
        TITLE=title,
        YEAR=year,
        SEASON_EPISODE=se,
        SOURCE="site",
        SOURCE_PATH="/src",
        SOURCE_FILENAME=dest_fn,
        DEST="/media",
        DEST_PATH=dest_path,
        DEST_FILENAME=dest_fn,
        DST_BACKEND="local",
        DATE="2026-01-01",
    )


def _seed(db_session):
    rows = [
        _mk(100, "/media/movie/A(2020)", "A.2020.1080p.WEB-DL.H265.mkv", "A", "2020"),
        _mk(100, "/media/movie/A(2020)", "A.2020.2160p.BluRay.Remux.mkv", "A", "2020"),
        _mk(200, "/media/movie/B(2021)", "B.2021.1080p.BluRay.mkv", "B", "2021"),
        _mk(300, "/media/tv/C", "C.S01E01.mkv", "C", "2022"),
        _mk(300, "/media/tv/C2", "C.S01E03.mkv", "C", "2022"),
        _mk(400, "/media/gof/电影", "Same.2023.mkv", "D", "2023"),
        _mk(400, "/media/favorites/电影", "Same.2023.mkv", "D", "2023"),
    ]
    for row in rows:
        db_session.add(TRANSFERHISTORY(**row))
    db_session.commit()


class TestGetMultiVersionGroups:
    def test_returns_only_multi_version_works(self, db_session):
        _seed(db_session)
        repo = _TestableTransferRepository(db_session)
        groups = repo.get_multi_version_groups()
        tmdb_ids = {g["tmdb_id"] for g in groups}
        assert 100 in tmdb_ids  # 同目录 2 文件 -> 多版本
        assert 300 in tmdb_ids  # 跨目录 -> 多版本
        assert 400 in tmdb_ids  # 同文件名不同目录 -> 多版本
        assert 200 not in tmdb_ids  # 单文件 -> 不算

    def test_same_dir_multiple_files_counts(self, db_session):
        """同一目录内多个不同文件也应识别为多版本（dir_count 相同但 file_count>1）。"""
        _seed(db_session)
        repo = _TestableTransferRepository(db_session)
        groups = {g["tmdb_id"]: g for g in repo.get_multi_version_groups()}
        assert groups[100]["file_count"] == 2

    def test_same_filename_different_dirs_counts(self, db_session):
        _seed(db_session)
        repo = _TestableTransferRepository(db_session)
        groups = {g["tmdb_id"]: g for g in repo.get_multi_version_groups()}
        assert groups[400]["file_count"] == 2
        assert groups[400]["dir_count"] == 2


class _HistoryManagerStub:
    def __init__(self, infos):
        self._infos = infos

    def get_multi_version_groups(self, limit=100):
        return [
            {"tmdb_id": 100, "title": "A", "year": "2020", "dir_count": 1, "file_count": 2}
        ]

    def get_transfer_info_by(self, tmdbid, season=None, season_episode=None):
        return [i for i in self._infos if int(getattr(i, "TMDBID", 0)) == int(tmdbid)]


class TestFileIndexMultiVersion:
    def test_get_versions_marks_spec_and_exists(self, db_session):
        _seed(db_session)
        infos = db_session.query(TRANSFERHISTORY).filter(TRANSFERHISTORY.TMDBID == 100).all()
        svc = FileIndexService.__new__(FileIndexService)
        svc._history_manager = _HistoryManagerStub(infos)
        versions = svc.get_versions(tmdb_id=100)
        assert len(versions) == 2
        # 规格解析应识别出分辨率/来源（不存在磁盘时 exists=False）
        assert versions[0]["spec"]
        assert versions[0]["exists"] is False
        assert versions[0]["dest_filename"]

    def test_list_duplicates_aggregates(self, db_session):
        _seed(db_session)
        infos = db_session.query(TRANSFERHISTORY).all()
        svc = FileIndexService.__new__(FileIndexService)
        svc._history_manager = _HistoryManagerStub(infos)
        dups = svc.list_duplicates()
        assert len(dups) == 1
        assert dups[0]["tmdb_id"] == 100
        assert len(dups[0]["versions"]) == 2
