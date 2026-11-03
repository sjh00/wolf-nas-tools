"""旧版本保留策略：源消失 / 版本替换。

真实使用有三种互斥诉求，不能用同一个默认行为覆盖：

1. 想留着  —— qb 里清理种子，媒体库文件必须留着（默认）
2. 想同步删 —— 删源等于删库
3. 想更新   —— 新版入库后，旧版允许被清掉

早期实现只有「永不自动删除」，所以"想同步删"做不到；而"想更新"卡在
两处：同步历史按目录记账、移除记录时只清了文件级黑名单，目录级那条
同步历史留着，导致内容再也无法重新识别入库。

本模块锁定策略语义与「默认绝不删除」这条安全线。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.transfer.retention_service import (
    RetentionPolicy,
    RetentionService,
    RetentionSweep,
)


def _record(**kw):
    base = {
        "ID": 1,
        "SOURCE_PATH": "/btstore/tv/Show",
        "SOURCE_FILENAME": "Show.S01E01.mkv",
        "DEST_PATH": "/medialink/TV/Show (2024)/Season 1",
        "DEST_FILENAME": "Show - S01E01.mkv",
        "DST_BACKEND": "local",
        "IDENTITY_ID": "01ABC",
        "SEASON_EPISODE": "S01 E01",
        "SOURCE_STATE": "present",
        "RETENTION_POLICY": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _service(source_exists=False):
    history = MagicMock()
    history.update_transfer_file_state.return_value = None
    history.update_retention_policy.return_value = True
    history.get_same_episode_records.return_value = []
    history.delete_transfer_logs.return_value = None

    files = MagicMock()
    svc = RetentionService(history=history, file_service=files)
    svc._source_exists = lambda record: source_exists  # type: ignore[method-assign]
    return svc, history, files


class TestPolicyNormalization:
    def test_known_values(self):
        assert RetentionPolicy.normalize("keep") == "keep"
        assert RetentionPolicy.normalize("sync_delete") == "sync_delete"
        assert RetentionPolicy.normalize("replace") == "replace"

    @pytest.mark.parametrize("value", [None, "", "  ", "unknown", "DELETE", 123])
    def test_falls_back_to_keep(self, value):
        # 未知/脏值一律按最安全的 keep 处理
        assert RetentionPolicy.normalize(value) == "keep"


class TestSourceMissing:
    def test_keep_marks_but_never_deletes(self):
        svc, history, files = _service(source_exists=False)
        record = _record(RETENTION_POLICY="keep")
        stats = svc.apply_source_missing([record])
        assert stats["marked"] == 1
        assert stats["deleted"] == 0
        files.delete_media_file.assert_not_called()
        history.update_transfer_file_state.assert_called()

    def test_default_none_policy_never_deletes(self):
        svc, _history, files = _service(source_exists=False)
        record = _record(RETENTION_POLICY=None)
        stats = svc.apply_source_missing([record])
        assert stats["deleted"] == 0
        files.delete_media_file.assert_not_called()

    def test_sync_delete_removes_library_file(self):
        svc, history, files = _service(source_exists=False)
        record = _record(RETENTION_POLICY="sync_delete")
        stats = svc.apply_source_missing([record])
        assert stats["deleted"] == 1
        files.delete_media_file.assert_called_once()
        args, kwargs = files.delete_media_file.call_args
        assert args[0] == record.DEST_PATH
        assert args[1] == record.DEST_FILENAME

    def test_existing_source_is_skipped(self):
        svc, history, files = _service(source_exists=True)
        record = _record(RETENTION_POLICY="sync_delete")
        stats = svc.apply_source_missing([record])
        assert stats == {"marked": 0, "deleted": 0, "failed": 0}
        files.delete_media_file.assert_not_called()

    def test_already_marked_missing_not_reprocessed(self):
        svc, history, files = _service(source_exists=False)
        record = _record(RETENTION_POLICY="sync_delete", SOURCE_STATE="missing")
        stats = svc.apply_source_missing([record])
        assert stats["marked"] == 0
        files.delete_media_file.assert_not_called()

    def test_delete_failure_counted_not_raised(self):
        svc, _history, files = _service(source_exists=False)
        files.delete_media_file.side_effect = RuntimeError("boom")
        record = _record(RETENTION_POLICY="sync_delete")
        stats = svc.apply_source_missing([record])
        assert stats["failed"] == 1
        assert stats["deleted"] == 0


class TestReplaceOlderVersions:
    def test_replaces_older_with_replace_policy(self):
        old = _record(ID=2, RETENTION_POLICY="replace", DEST_FILENAME="Show - S01E01 - 1080p.mkv")
        new = _record(ID=9, RETENTION_POLICY=None)
        history = MagicMock()
        history.get_same_episode_records.return_value = [new, old]
        files = MagicMock()
        svc = RetentionService(history=history, file_service=files)

        removed = svc.replace_older_versions(new)
        assert removed == 1
        history.delete_transfer_logs.assert_called_once_with([2])

    def test_keep_policy_older_untouched(self):
        old = _record(ID=2, RETENTION_POLICY="keep")
        new = _record(ID=9)
        history = MagicMock()
        history.get_same_episode_records.return_value = [new, old]
        files = MagicMock()
        svc = RetentionService(history=history, file_service=files)

        assert svc.replace_older_versions(new) == 0
        files.delete_media_file.assert_not_called()

    def test_does_not_delete_itself(self):
        new = _record(ID=9, RETENTION_POLICY="replace")
        history = MagicMock()
        history.get_same_episode_records.return_value = [new]
        files = MagicMock()
        svc = RetentionService(history=history, file_service=files)
        assert svc.replace_older_versions(new) == 0
        files.delete_media_file.assert_not_called()


class TestSweepSafety:
    def test_no_records_means_no_action(self):
        history = MagicMock()
        history.get_records_for_retention.return_value = []
        history.get_replace_candidates.return_value = []
        files = MagicMock()
        sweep = RetentionSweep(history=history)
        sweep._service = RetentionService(history=history, file_service=files)
        stats = sweep.sweep()
        assert stats["deleted"] == 0
        assert stats["replaced"] == 0
        files.delete_media_file.assert_not_called()


class TestSetPolicy:
    def test_set_policy_normalizes(self):
        history = MagicMock()
        history.update_retention_policy.return_value = True
        svc = RetentionService(history=history)
        assert svc.set_policy([1, 2], "REPLACE") == 2
        history.update_retention_policy.assert_any_call(1, "replace")

    def test_invalid_policy_falls_back_to_keep(self):
        history = MagicMock()
        history.update_retention_policy.return_value = True
        svc = RetentionService(history=history)
        svc.set_policy([3], "whatever")
        history.update_retention_policy.assert_called_with(3, "keep")
