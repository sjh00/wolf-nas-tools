"""回归测试：电影按 TMDB 身份去重，杜绝「标题漂移导致同一部片重复入库」。

真实故障：TMDB 社区译名被灌入广告（如「某片网：4488569.com 独行月球」），
刮削后目录名随之变化——`独行月球 (2022)/` 变成 `淫片网… (2022)/`。
转移侧此前只按「标题生成的目标路径」判存在，路径一变就判为不存在，
于是同一部片被再次转移，媒体库里出现两份。

修复：转移前按 tmdb_id 查已入库版本，并用「文件大小一致」或「分辨率+版本标记一致」
确认是同一份内容；规格不同（1080p vs 2160p）仍按多版本放行。
"""

import os

import pytest

from app.domain.mediatypes import MediaType
from app.media.models import MediaInfo
from app.services.transfer.filetransfer_service import (
    FileTransferService,
    _spec_signature,
    _spec_signature_from_filename,
)


def _media(pix="2160p", effect="", tmdb_id=801803, title="独行月球") -> MediaInfo:
    return MediaInfo(
        type=MediaType.MOVIE,
        tmdb_id=tmdb_id,
        title=title,
        year="2022",
        resource_pix=pix,
        resource_effect=effect,
    )


def _row(dest_path: str, dest_filename: str, source_path: str = "/src/original.mkv"):
    """构造历史记录替身（字段名与 adapter 暴露一致，均为小写）."""

    class _Row:
        pass

    row = _Row()
    row.dest_path = dest_path
    row.dest_filename = dest_filename
    row.source_path = source_path
    return row


@pytest.fixture
def service(tmp_path, monkeypatch):
    """最小可用服务：只装配去重所需的 history/existence。"""
    svc = FileTransferService.__new__(FileTransferService)

    class _History:
        def __init__(self):
            self.by_tmdb = []
            self.by_source = None

        def get_transfer_info_by(self, tmdbid, season=None, season_episode=None):
            return self.by_tmdb

        def get_by_source(self, source_full_path):
            return self.by_source

    svc._history = _History()
    svc._existence = None
    return svc


def _touch(path: str, size: int) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"x" * size)
    return path


class TestSpecSignature:
    def test_includes_resolution_and_edition(self):
        assert _spec_signature(_media(pix="2160p")) == "2160p"
        assert _spec_signature(_media(pix="1080p", effect="IMAX")) == "1080p/imax"

    def test_ignores_missing(self):
        assert _spec_signature(_media(pix="", effect="")) == ""

    def test_from_filename_matches_media(self):
        """规范命名解析出的规格应与原 media 一致（仅差标题）"""
        assert _spec_signature_from_filename("独行月球 (2022) - 2160p.mkv") == "2160p"
        assert _spec_signature_from_filename("某片名 (2022) - 1080p.mkv") == "1080p"

    def test_from_filename_handles_garbage(self):
        assert _spec_signature_from_filename("") == ""
        assert _spec_signature_from_filename("x") == ""


class TestMovieDuplicateTarget:
    def test_title_drift_same_spec_is_duplicate(self, service, tmp_path):
        """标题漂移 + 同分辨率 → 判重复（大小不同，走规格判定）"""
        lib = tmp_path / "独行月球 (2022)"
        _touch(str(lib / "独行月球 (2022) - 2160p.mkv"), 1000)
        service._history.by_tmdb = [_row(str(lib), "独行月球 (2022) - 2160p.mkv")]

        src = _touch(str(tmp_path / "src.mkv"), 777)
        got = service._movie_duplicate_target(_media(pix="2160p"), src)
        assert got, "同规格应判为重复"
        assert got.endswith("独行月球 (2022) - 2160p.mkv")

    def test_same_size_is_duplicate(self, service, tmp_path):
        """大小完全一致 → 同一份文件，即使规格解析不出也判重复"""
        lib = tmp_path / "lib"
        _touch(str(lib / "some.mkv"), 1500)
        service._history.by_tmdb = [_row(str(lib), "some.mkv")]

        src = _touch(str(tmp_path / "src.mkv"), 1500)
        assert service._movie_duplicate_target(_media(pix=""), src)

    def test_different_spec_allows_multi_version(self, service, tmp_path):
        """1080p 相对已入库 2160p → 多版本，必须放行"""
        lib = tmp_path / "lib"
        _touch(str(lib / "独行月球 (2022) - 2160p.mkv"), 1000)
        service._history.by_tmdb = [_row(str(lib), "独行月球 (2022) - 2160p.mkv")]

        src = _touch(str(tmp_path / "src.mkv"), 300)
        assert service._movie_duplicate_target(_media(pix="1080p"), src) == ""

    def test_no_history_allows(self, service, tmp_path):
        service._history.by_tmdb = []
        src = _touch(str(tmp_path / "src.mkv"), 100)
        assert service._movie_duplicate_target(_media(), src) == ""

    def test_missing_target_allows_rebuild(self, service, tmp_path):
        """历史记录的目标已被删除 → 允许重新入库，不能永久挡住"""
        service._history.by_tmdb = [_row(str(tmp_path / "gone"), "gone.mkv")]
        src = _touch(str(tmp_path / "src.mkv"), 100)
        assert service._movie_duplicate_target(_media(), src) == ""

    def test_no_tmdb_id_allows(self, service, tmp_path):
        src = _touch(str(tmp_path / "src.mkv"), 100)
        assert service._movie_duplicate_target(_media(tmdb_id=0), src) == ""

    def test_history_query_failure_allows(self, service, tmp_path):
        """查历史异常时放行：宁可多转移一次，也不能误挡真实文件"""

        def boom(*args, **kwargs):
            raise RuntimeError("db down")

        service._history.get_transfer_info_by = boom
        src = _touch(str(tmp_path / "src.mkv"), 100)
        assert service._movie_duplicate_target(_media(), src) == ""

    def test_picks_existing_among_multiple(self, service, tmp_path):
        """多条历史中只要有一条同规格命中即判重复"""
        gone = tmp_path / "gone"
        lib = tmp_path / "lib"
        _touch(str(lib / "独行月球 (2022) - 2160p.mkv"), 1000)
        service._history.by_tmdb = [
            _row(str(gone), "gone.mkv"),
            _row(str(lib), "独行月球 (2022) - 2160p.mkv"),
        ]
        src = _touch(str(tmp_path / "src.mkv"), 777)
        assert service._movie_duplicate_target(_media(pix="2160p"), src)


class TestPollutedTitleDuplicate:
    """端到端语义：被灌广告的标题不得再产生一份"""

    def test_polluted_title_requesting_same_movie_is_skipped(self, service, tmp_path):
        lib = tmp_path / "独行月球 (2022)"
        _touch(str(lib / "独行月球 (2022) - 2160p.mkv"), 1000)
        service._history.by_tmdb = [_row(str(lib), "独行月球 (2022) - 2160p.mkv")]

        src = _touch(str(tmp_path / "淫片网 4488329.com 黄漫片网 4488569.com.mkv"), 777)
        # 标题被污染，但 TMDB 身份与规格（2160p）都指向同一部片
        polluted = _media(pix="2160p", title="淫片网 448832𝟵.com  黄漫片网 448856𝟵.com")
        got = service._movie_duplicate_target(polluted, src)
        assert got, "被污染的标题不应导致重复入库"
