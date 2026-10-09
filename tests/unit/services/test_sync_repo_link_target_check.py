"""目录同步（重命名/转移模式）：目标被删除后应清理黑名单并重新同步。

回归：`_do_transfer` 此前仅凭转移黑名单/同步历史直接跳过，
目标媒体文件被删除后不再重新硬链接。
"""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

from app.services.sync_engine import SyncEngine


def _engine(dest_exists: bool):
    svc = SyncEngine.__new__(SyncEngine)
    svc._history_repo = MagicMock()
    svc._history_repo.is_sync_in_history.return_value = False
    svc._transfer = MagicMock()
    svc._transfer._blacklist.is_exists.return_value = True
    svc._pipeline = MagicMock()
    svc._pipeline.process.return_value = (True, "ok")
    setattr(svc, "_destination_exists_for_source", MagicMock(return_value=dest_exists))
    return svc


def _cfg(source):
    return SimpleNamespace(
        id="1",
        source=str(source),
        dest="/lib/anime",
        unknown="/lib/unknown",
        operation="link",
        dst_backend_id="local",
        rename=True,
    )


def test_target_deleted_clears_blacklist_and_resyncs(tmp_path):
    src = tmp_path / "E01.mkv"
    src.write_bytes(b"x")
    svc = _engine(dest_exists=False)

    svc._do_transfer(str(src), cast(Any, _cfg(tmp_path)))

    assert cast(Any, svc._transfer)._blacklist.delete.called
    assert cast(Any, svc._pipeline).process.call_count == 1


def test_target_present_skips_resync(tmp_path):
    src = tmp_path / "E01.mkv"
    src.write_bytes(b"x")
    svc = _engine(dest_exists=True)

    svc._do_transfer(str(src), cast(Any, _cfg(tmp_path)))

    cast(Any, svc._transfer)._blacklist.delete.assert_not_called()
    cast(Any, svc._pipeline).process.assert_not_called()
