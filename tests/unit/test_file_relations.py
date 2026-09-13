"""FileIndexService.get_file_relations 单元测试 — 源/媒体库文件关系分析."""

from unittest.mock import MagicMock

from app.services.file_index_service import FileIndexService


class _Rec:
    def __init__(
        self,
        rid,
        title,
        src_path,
        src_fn,
        dst_path,
        dst_fn,
        season="",
        year="2020",
        tmdb=100,
    ):
        self.ID = rid
        self.TITLE = title
        self.YEAR = year
        self.SEASON_EPISODE = season
        self.TMDBID = tmdb
        self.SOURCE_PATH = src_path
        self.SOURCE_FILENAME = src_fn
        self.DEST_PATH = dst_path
        self.DEST_FILENAME = dst_fn


def _svc(records):
    svc = FileIndexService.__new__(FileIndexService)
    svc._history_manager = MagicMock()
    svc._history_manager.get_transfer_history.return_value = (len(records), records)
    svc._find_hardlinks = MagicMock(return_value=[])
    return svc


class TestFileRelations:
    def test_classifies_by_disk_presence(self, tmp_path):
        src = tmp_path / "seed"
        src.mkdir()
        (src / "A.mkv").write_text("x")
        dst = tmp_path / "movie" / "A"
        dst.mkdir(parents=True)
        (dst / "A.mkv").write_text("x")
        # A: both（源+目标都在）
        # B: only_source（源在，目标不在）
        # C: only_dest（目标在，源不在）
        (src / "B.mkv").write_text("x")  # B 源文件存在，目标不存在
        (dst / "C.mkv").write_text("x")  # C 媒体库目标存在，源不存在
        records = [
            _Rec(1, "A2020", str(src), "A.mkv", str(dst), "A.mkv"),
            _Rec(2, "B2020", str(src), "B.mkv", str(tmp_path / "movie2" / "B"), "B.mkv"),
            _Rec(3, "C2020", str(tmp_path / "seed2"), "C.mkv", str(dst), "C.mkv"),
        ]
        svc = _svc(records)
        res = svc.get_file_relations()

        by_id = {r["id"]: r["state"] for r in res["items"]}
        assert by_id[1] == "both"
        assert by_id[2] == "only_source"
        assert by_id[3] == "only_dest"
        assert res["state_counts"]["both"] == 1
        assert res["state_counts"]["only_source"] == 1
        assert res["state_counts"]["only_dest"] == 1

    def test_state_and_search_filter(self, tmp_path):
        src = tmp_path / "seed"
        src.mkdir()
        (src / "A.mkv").write_text("x")
        records = [_Rec(1, "ALPHA2020", str(src), "A.mkv", str(tmp_path / "m"), "A.mkv")]
        svc = _svc(records)
        # search 命中
        res = svc.get_file_relations(search="alpha")
        assert res["total"] == 1
        # search 不命中
        res = svc.get_file_relations(search="nomatch")
        assert res["total"] == 0
        # state 过滤（A.mkv 在磁盘不存在目标 -> only_source）
        res = svc.get_file_relations(state="only_source")
        assert res["total"] == 1

    def test_page_offset(self, tmp_path):
        src = tmp_path / "seed"
        src.mkdir()
        for i in range(5):
            (src / f"A{i}.mkv").write_text("x")
        records = [_Rec(i, f"T{i}", str(src), f"A{i}.mkv", str(tmp_path / "m"), f"A{i}.mkv") for i in range(5)]
        svc = _svc(records)
        res = svc.get_file_relations(page=2, page_size=2)
        assert len(res["items"]) == 2
        assert res["total"] == 5
