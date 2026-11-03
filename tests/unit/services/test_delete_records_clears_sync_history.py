"""移除识别记录必须连带清掉同步历史。

同步引擎的跳过条件是「转移历史 / 同步历史 / 黑名单任一命中」。
其中 SYNCHISTORY 按**目录**记账（同步监听的单位），而识别记录里
SOURCE_PATH 是目录、SOURCE_FILENAME 才是文件。

早期 `delete_records` 只按「目录/文件」拼接的完整路径删黑名单，
目录级那条同步历史留着 —— 用户移除记录后，同步引擎仍认为已同步，
内容再也无法重新识别入库。用户想换版本时就会卡在这里。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.transfer.history_action_service import HistoryActionService


def _record(rid=1, source_path="/btstore/tv/Show", source_filename="Show.S01E01.mkv"):
    return SimpleNamespace(
        ID=rid,
        SOURCE_PATH=source_path,
        SOURCE_FILENAME=source_filename,
        DEST_PATH="/medialink/TV/Show (2024)/Season 1",
        DEST_FILENAME="Show - S01E01.mkv",
        DST_BACKEND="local",
    )


def _service(records):
    history = MagicMock()
    history.update_transfer_file_state.return_value = None
    history.delete_transfer_logs.return_value = None
    history.delete_transfer_blacklist.return_value = None
    history.delete_sync_history_for_source.return_value = 1
    svc = HistoryActionService(history_manager=history, file_service=MagicMock(), delete_history=MagicMock())

    def load(logids):
        return [r for r in records if r.ID in logids]

    svc._load_records = load  # type: ignore[method-assign]
    return svc, history


class TestDeleteRecordsClearsSyncHistory:
    def test_clears_sync_history_for_source_dir(self):
        record = _record()
        svc, history = _service([record])

        svc.delete_records([1])

        # 必须按「源目录」清，而不是只清文件级路径
        history.delete_sync_history_for_source.assert_called_once_with("/btstore/tv/Show")

    def test_still_clears_blacklist_and_record(self):
        record = _record()
        svc, history = _service([record])

        svc.delete_records([1])

        history.delete_transfer_logs.assert_called_once_with([1])
        history.delete_transfer_blacklist.assert_called_once_with("/btstore/tv/Show/Show.S01E01.mkv")

    def test_missing_record_is_skipped(self):
        svc, history = _service([])
        results = svc.delete_records([99])
        assert results[0]["status"] == "skipped"
        history.delete_sync_history_for_source.assert_not_called()

    def test_sync_cleanup_failure_does_not_abort(self):
        """清理同步历史失败不应阻止记录删除（记录删了更重要）."""
        record = _record()
        svc, history = _service([record])
        history.delete_sync_history_for_source.side_effect = RuntimeError("db locked")

        results = svc.delete_records([1])

        assert results[0]["status"] == "deleted"
        history.delete_transfer_logs.assert_called_once()
