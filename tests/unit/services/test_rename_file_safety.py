"""文件重命名安全测试：仅允许同目录内重命名，杜绝路径穿越。"""

from app.services.sync_service import SyncService


def test_rename_file_strips_path_traversal(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    src = lib / "old.mkv"
    src.write_text("x", encoding="utf-8")

    result = SyncService.rename_file(str(src), "../../evil.mkv")

    assert result.success is True
    assert (lib / "evil.mkv").exists()  # 仅取文件名，落在原目录
    assert not (tmp_path.parent / "evil.mkv").exists()  # 未逃逸


def test_rename_file_rejects_parent_dir_name(tmp_path):
    src = tmp_path / "a.mkv"
    src.write_text("x", encoding="utf-8")

    result = SyncService.rename_file(str(src), "..")

    assert result.success is False
