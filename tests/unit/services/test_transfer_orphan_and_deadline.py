"""遗漏对账与「预检不拖垮请求」。

三个真实问题：
1. 多版本预检在 HTTP 请求路径上做 TMDB 识别 + 逐文件 ``find -inum``，
   实测单次 POST /api/download/tasks 平均 11.8s、峰值 35s，逼近前端 60s 超时；
   一旦超时用户看到「失败」，而后端其实还在跑 → 误以为失败而重复添加。
2. ``transfer_bluray_dir`` 无论有没有真的转移都记黑名单，导致「目标已存在、
   全部跳过」的目录被永久标记，文件既无记录也不再处理，界面上完全不可见。
3. 黑名单只有 PATH，没有结果与时间，命中即静默 return，无法发现上述误标。
"""

import time

import pytest

from app.utils.deadline import run_with_deadline


class TestRunWithDeadline:
    def test_returns_value_when_fast(self):
        assert run_with_deadline(lambda: 42, 5.0, default=None) == 42

    def test_returns_default_on_timeout(self):
        started = time.monotonic()
        result = run_with_deadline(lambda: time.sleep(1.5) or "late", 0.2, default="fallback")
        cost = time.monotonic() - started
        assert result == "fallback"
        # 必须立刻返回，而不是等到函数跑完
        assert cost < 1.0

    def test_zero_timeout_runs_inline(self):
        box = []
        run_with_deadline(lambda: box.append(1), 0, default=None)
        assert box == [1]

    def test_exception_propagates(self):
        def boom():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            run_with_deadline(boom, 5.0, default=None)

    def test_timeout_does_not_block_later_calls(self):
        """超时放弃的那次仍在后台跑，但不能卡住后续调用。"""
        run_with_deadline(lambda: time.sleep(1.0), 0.1, default=None)
        started = time.monotonic()
        assert run_with_deadline(lambda: "ok", 5.0, default=None) == "ok"
        assert time.monotonic() - started < 0.8


class TestTransferDirBlacklist:
    """目录转移只在「真的转移过」时记黑名单。"""

    @staticmethod
    def _engine():
        from app.services.transfer_engine import TransferEngine

        engine = TransferEngine()

        class _Recorder:
            def __init__(self):
                self.paths = []

            def insert(self, path):
                self.paths.append(path)

        engine._blacklist = _Recorder()
        return engine

    def test_all_skipped_does_not_blacklist(self, tmp_path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        (src / "a.mkv").write_bytes(b"x")
        (dst / "a.mkv").write_bytes(b"x")  # 目标已存在 → 全部跳过

        engine = self._engine()
        engine.transfer_bluray_dir(str(src), str(dst), "link")

        assert engine._blacklist.paths == [], "全部跳过时不能把源目录标记为已处理"

    def test_partial_transfer_blacklists(self, tmp_path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        (src / "a.mkv").write_bytes(b"x")
        (src / "b.mkv").write_bytes(b"y")
        (dst / "a.mkv").write_bytes(b"x")  # 只有一个已存在

        engine = self._engine()
        engine.transfer_bluray_dir(str(src), str(dst), "link")

        assert str(src) in engine._blacklist.paths
        assert (dst / "b.mkv").exists()

    def test_transfer_dir_returns_counts(self, tmp_path):
        src = tmp_path / "s"
        dst = tmp_path / "d"
        src.mkdir()
        dst.mkdir()
        (src / "a.mkv").write_bytes(b"1")
        (src / "b.mkv").write_bytes(b"2")
        (dst / "b.mkv").write_bytes(b"2")

        moved, skipped = self._engine().transfer_dir(str(src), str(dst), "link", record_blacklist=False)
        assert (moved, skipped) == (1, 1)


class TestGetVersionsSkipsHardlinkScan:
    """多版本检测不再默认逐文件查硬链接（那是 N 次 find 子进程）。"""

    def test_default_no_hardlinks(self, tmp_path, monkeypatch):
        from app.services.file_index_service import FileIndexService

        svc = FileIndexService.__new__(FileIndexService)

        class _Row:
            DEST_PATH = str(tmp_path)
            DEST_FILENAME = "a.mkv"
            SOURCE_FILENAME = "src.mkv"
            SEASON_EPISODE = "S01 E01"
            DATE = "2026-01-01"

        class _History:
            def get_transfer_info_by(self, tmdbid=None):
                return [_Row()]

        svc._history_manager = _History()  # type: ignore[attr-defined]
        (tmp_path / "a.mkv").write_bytes(b"x")

        called = []
        monkeypatch.setattr(
            FileIndexService, "_find_hardlinks", lambda self, path: called.append(path) or []
        )
        versions = svc.get_versions(123)
        assert versions and versions[0]["hardlinks"] == []
        assert called == [], "默认路径不能触发硬链接扫描"

    def test_opt_in_still_works(self, tmp_path, monkeypatch):
        from app.services.file_index_service import FileIndexService

        svc = FileIndexService.__new__(FileIndexService)

        class _Row:
            DEST_PATH = str(tmp_path)
            DEST_FILENAME = "a.mkv"
            SOURCE_FILENAME = "src.mkv"
            SEASON_EPISODE = ""
            DATE = ""

        class _History:
            def get_transfer_info_by(self, tmdbid=None):
                return [_Row()]

        svc._history_manager = _History()  # type: ignore[attr-defined]
        (tmp_path / "a.mkv").write_bytes(b"x")

        monkeypatch.setattr(FileIndexService, "_find_hardlinks", lambda self, path: ["/sibling.mkv"])
        versions = svc.get_versions(123, with_hardlinks=True)
        assert versions[0]["hardlinks"] == ["/sibling.mkv"]


class TestBlacklistRepoListing:
    def test_repository_exposes_all_paths(self):
        """对账依赖「列出全部黑名单」；缺这个方法就无法发现静默跳过。"""
        from app.db.repositories.transfer_repository import TransferRepository

        assert hasattr(TransferRepository, "get_all_transfer_blacklist")
