"""MediaConsistencyService 单元测试 — 跨盘整理感知/一致性校验."""

from unittest.mock import MagicMock

import pytest

from app.services.media_consistency_service import MediaConsistencyService


class _Rec:
    def __init__(self, rid, dest_path, dest_filename):
        self.ID = rid
        self.DEST_PATH = dest_path
        self.DEST_FILENAME = dest_filename


@pytest.fixture
def svc():
    history = MagicMock()
    file_index = MagicMock()
    s = MediaConsistencyService(history_manager=history, file_index_service=file_index)
    s._history = history
    s._file_index = file_index
    return s


class TestConsistency:
    def test_existing_dest_untouched(self, svc, tmp_path):
        """DEST 存在 -> 不修正"""
        d = tmp_path / "movie" / "A"
        d.mkdir(parents=True)
        f = d / "A.2020.mkv"
        f.write_text("x")
        rec = _Rec(1, str(d), "A.2020.mkv")
        svc._history.get_transfer_history.return_value = (1, [rec])
        result = svc.check_library_consistency()
        assert result["checked"] == 1
        assert result["fixed"] == 0
        assert result["missing"] == 0
        svc._history.update_transfer_dest.assert_not_called()

    def test_moved_dest_fixed_when_unique_candidate(self, svc, tmp_path):
        """DEST 不存在但索引有唯一同名候选 -> 更新记录"""
        old_dir = tmp_path / "movie" / "A"
        old_dir.mkdir(parents=True)
        rec = _Rec(2, str(old_dir), "A.2020.mkv")  # 旧 DEST 指向不存在的位置
        new_path = str(tmp_path / "other" / "A")  # 新位置（模拟移动后）
        svc._history.get_transfer_history.return_value = (1, [rec])
        svc._history.update_transfer_dest.return_value = True
        svc._file_index.find_by_name.return_value = [
            {"name": "A.2020.mkv", "path": f"{new_path}/A.2020.mkv"}
        ]

        result = svc.check_library_consistency()
        assert result["fixed"] == 1
        svc._history.update_transfer_dest.assert_called_once()
        assert svc._history.update_transfer_dest.call_args.kwargs["logid"] == 2

    def test_missing_when_no_candidate(self, svc, tmp_path):
        """DEST 不存在且无候选 -> 标记丢失"""
        old_dir = tmp_path / "movie" / "A"
        old_dir.mkdir(parents=True)
        rec = _Rec(3, str(old_dir), "A.2020.mkv")
        svc._history.get_transfer_history.return_value = (1, [rec])
        svc._file_index.find_by_name.return_value = []
        result = svc.check_library_consistency()
        assert result["missing"] == 1
        assert result["missing_records"][0]["id"] == 3
