"""移除记录时同时清理文件：顺序必须先文件后记录。

记录一旦先删掉，就再也无法从记录里找回文件路径，残留文件会变成无法回收的
孤儿。这条用例就是防止顺序被改回去。
"""

from app.services.transfer.history_action_service import HistoryActionService
from app.services.transfer.media_file_deletion_service import MediaFileDeletionService


class _Record:
    def __init__(self, rid):
        self.ID = rid
        self.SOURCE_PATH = "/src"
        self.SOURCE_FILENAME = f"ep{rid}.mkv"
        self.DEST_PATH = "/lib"
        self.DEST_FILENAME = f"ep{rid}.mkv"
        self.SOURCE_STATE = None
        self.SOURCE_DELETED_AT = None
        self.DEST_STATE = None
        self.DEST_DELETED_AT = None


class _History:
    def __init__(self):
        self.deleted_logs: list[list[int]] = []
        self.blacklist: list[str] = []

    def get_transfer_info_by_id(self, logid):
        return _Record(logid) if logid in (1, 2) else None

    def delete_transfer_logs(self, ids):
        self.deleted_logs.append(list(ids))

    def delete_transfer_blacklist(self, path):
        self.blacklist.append(path)

    def delete_sync_history_for_source(self, path):
        return None

    def update_transfer_file_state(self, *args, **kwargs):
        return None


class _Files(MediaFileDeletionService):
    """只提供测试需要的两个方法，其余行为不用到."""

    def __init__(self):  # noqa: D107 - 不调用父类构造：本用例不碰真实文件
        pass

    def resolve_backend_by_id(self, backend_id):
        return None

    def delete_media_file(self, *args, **kwargs):
        return None


def _service(exists=True):
    history = _History()
    calls: list[str] = []

    def _delete_history(logids, flag):
        calls.append(f"files:{flag}")

    svc = HistoryActionService(history, _Files(), _delete_history)
    # 文件是否存在由「文件实际状态」决定，这里直接控制判定结果
    svc._target_exists = lambda record, target: exists  # type: ignore[method-assign]
    return svc, history, calls


class TestDeleteRecordsWithFiles:
    def test_file_targets_are_deleted_before_records(self):
        svc, history, calls = _service()

        svc.delete_records_with_files([1], ["source"])

        assert calls and calls[0].startswith("files:")
        assert history.deleted_logs, "记录必须在文件处理之后才删除"

    def test_no_targets_only_deletes_records(self):
        svc, history, calls = _service()

        svc.delete_records_with_files([1], [])

        assert calls == []
        assert history.deleted_logs == [[1]]

    def test_both_targets_map_to_del_all(self):
        svc, _history, calls = _service()

        svc.delete_records_with_files([1], ["source", "library"])

        assert calls == ["files:del_all"]

    def test_library_only_maps_to_del_dest(self):
        svc, _history, calls = _service()

        svc.delete_records_with_files([1], ["library"])

        assert calls == ["files:del_dest"]

    def test_torrent_target_is_not_treated_as_file(self):
        """种子由下载器处理，不能当成文件目标传给文件删除逻辑."""
        svc, history, calls = _service()

        svc.delete_records_with_files([1], ["torrent"])

        assert calls == []
        assert history.deleted_logs == [[1]]

    def test_missing_record_is_reported(self):
        svc, _history, _calls = _service()

        results = svc.delete_records_with_files([99], ["source"])

        assert any(item["id"] == 99 and item["status"] == "skipped" for item in results)


class TestSourceRefs:
    def test_returns_locator_payload(self):
        svc, _history, _calls = _service()

        refs = svc.source_refs([1, 99])

        assert refs == [
            {"id": 1, "source_path": "/src", "source_filename": "ep1.mkv", "title": ""}
        ]
