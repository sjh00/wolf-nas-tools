"""目录同步（重命名/转移模式）：历史/黑名单命中后目标缺失也必须跳过。"""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

from app.services.sync_engine import SyncEngine


def _engine():
    svc = SyncEngine.__new__(SyncEngine)
    svc._history_repo = MagicMock()
    svc._history_repo.is_sync_in_history.return_value = False
    svc._history_repo.get_by_source.return_value = None
    svc._transfer = MagicMock()
    svc._transfer._blacklist.is_exists.return_value = True
    svc._pipeline = MagicMock()
    svc._pipeline.process.return_value = (True, "ok")
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


def _write_media(path):
    """写入满足默认最小媒体大小限制的稀疏文件."""
    with open(path, "wb") as handle:
        handle.truncate(151 * 1024 * 1024)


def test_target_deleted_does_not_clear_blacklist_or_resync(tmp_path):
    src = tmp_path / "E01.mkv"
    _write_media(src)
    svc = _engine()

    svc._do_transfer(str(src), cast(Any, _cfg(tmp_path)))

    assert not cast(Any, svc._transfer)._blacklist.delete.called
    assert cast(Any, svc._pipeline).process.call_count == 0


def test_transfer_history_hit_skips_even_when_target_missing(tmp_path):
    src = tmp_path / "E01.mkv"
    _write_media(src)
    svc = _engine()
    cast(Any, svc._transfer._blacklist.is_exists).return_value = False
    cast(Any, svc._history_repo.get_by_source).return_value = SimpleNamespace(
        dest_path="/lib/anime", dest_filename="E01.mkv"
    )

    svc._do_transfer(str(src), cast(Any, _cfg(tmp_path)))

    cast(Any, svc._pipeline).process.assert_not_called()


def test_target_present_skips_resync(tmp_path):
    src = tmp_path / "E01.mkv"
    _write_media(src)
    svc = _engine()

    svc._do_transfer(str(src), cast(Any, _cfg(tmp_path)))

    cast(Any, svc._transfer)._blacklist.delete.assert_not_called()
    cast(Any, svc._pipeline).process.assert_not_called()
