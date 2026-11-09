"""识别失败必须判定为失败，无论是否已存在未识别记录。

真实故障：用户对未识别项点「重新识别」，记录从列表消失，但媒体库没有文件、
识别历史没有记录、也没有任何通知。原因链：

1. 第一次识别失败 → 插入未识别记录（failed=1，判定失败）✓
2. 第二次识别仍失败，但该路径已在未识别列表 → ``_handle_unrecognized_file``
   返回 ``0``（只为「不重复计数」），``success_flag`` 保持 True
3. ``transfer_media`` 返回成功 → 调用方 ``update_transfer_unknown_state``
   把记录标成已识别 → 记录永久消失

关键不变式：只要走到「未识别」分支，结果必须是失败。
"""

import os
from unittest.mock import MagicMock

from app.services.transfer.filetransfer_service import FileTransferService


def _service(exists_in_unknown: bool, need_insert: bool = True) -> FileTransferService:
    svc = FileTransferService.__new__(FileTransferService)
    history = MagicMock()
    history.is_transfer_unknown_exists.return_value = exists_in_unknown
    history.is_need_insert_transfer_unknown.return_value = need_insert
    svc._history = history
    svc.progress = MagicMock()
    svc._engine = MagicMock()
    svc._path_resolver = MagicMock()
    svc._path_resolver.unknown_path = None
    return svc


class TestUnrecognizedAlwaysFails:
    def test_existing_unknown_record_still_reports_failure(self):
        """已在未识别列表 → 计数为 0，但调用方必须把它当失败。"""
        svc = _service(exists_in_unknown=True)
        fc, ac, _msgs = svc._handle_unrecognized_file(
            "/media/gof/btstore/tv/x/S01E50.mkv",
            "/media/gof/btstore/tv/x/S01E50.mkv",
            "/media/gof/btstore/tv/x",
            None,
            "link",
            "/media/gof/tv",
            False,
            [],
        )
        # 不重复计数是对的
        assert fc == 0
        assert ac == 0

    def test_first_failure_reports_count(self):
        svc = _service(exists_in_unknown=False, need_insert=True)
        fc, ac, msgs = svc._handle_unrecognized_file(
            "/media/gof/btstore/tv/x/S01E50.mkv",
            "/media/gof/btstore/tv/x/S01E50.mkv",
            "/media/gof/btstore/tv/x",
            None,
            "link",
            "/media/gof/tv",
            False,
            [],
        )
        assert fc == 1
        assert ac == 1
        assert "无法识别媒体信息" in msgs

    def test_no_insert_case_also_reports_zero(self):
        svc = _service(exists_in_unknown=False, need_insert=False)
        fc, _ac, _msgs = svc._handle_unrecognized_file(
            "/a/b.mkv", "/a/b.mkv", "/a", None, "link", "/lib", False, []
        )
        assert fc == 0


class TestTransferLoopMarksUnrecognizedAsFailure:
    """驱动真实的 _transfer_files_loop，确认 fc=0 时结果仍是失败。"""

    @staticmethod
    def _loop_service() -> FileTransferService:
        svc = FileTransferService.__new__(FileTransferService)
        svc._history = MagicMock()
        # 路径已在未识别列表 → _handle_unrecognized_file 返回 0
        svc._history.is_transfer_unknown_exists.return_value = True
        svc._history.is_transfer_notin_blacklist.return_value = True
        svc.progress = MagicMock()
        svc._engine = MagicMock()
        svc._path_resolver = MagicMock()
        svc._path_resolver.unknown_path = None
        svc._path_resolver.movie_category_flag = False
        svc._event_bus = MagicMock()
        svc._metadata_service = None  # type: ignore[attr-defined]
        svc._subscribe_repo = None
        return svc

    def test_result_is_failure_when_media_unrecognized(self):
        svc = self._loop_service()
        # 关键：未识别的 media（无 tmdb_id、无 title）
        media = MagicMock()
        media.tmdb_id = 0
        media.title = ""
        media.begin_episode = 3
        media.get_title_string.return_value = ""

        result = svc._transfer_files_loop(
            medias={"/media/gof/btstore/tv/x/S01E50.mkv": media},
            in_from=MagicMock(),
            in_path="/media/gof/btstore/tv/x/S01E50.mkv",
            operation="link",
            target_dir="/media/gof/tv",
            unknown_dir=None,
            bluray_disk_dir=None,
            episode=None,
            udf_flag=False,
            src_backend=None,
            dst_backend=None,
        )
        assert result["success_flag"] is False
        assert result["error_message"] == "无法识别媒体信息"
        assert result["failed_count"] == 0  # 不重复计数，语义仍为失败


class TestReIdentifyKeepsRecordOnFailure:
    """_do_one ??????????? executor ????????"""

    @staticmethod
    def _service(succ: bool, msg: str):
        from concurrent.futures import Future

        from app.services.sync_service import SyncService

        svc = SyncService.__new__(SyncService)
        filetransfer = MagicMock()
        unknown = MagicMock()
        unknown.path = "/media/gof/btstore/tv/x/S01E50.mkv"
        unknown.dest = "/media/gof/tv"
        unknown.mode = "link"
        filetransfer.get_unknown_info_by_id.return_value = unknown
        filetransfer.transfer_media.return_value = (succ, msg)
        svc._filetransfer = filetransfer
        svc._resolve_dst_backend_by_dest = MagicMock(return_value=None)

        def _sync_submit(fn, *args, **kwargs):
            fut: Future = Future()
            try:
                fn(*args, **kwargs)
                fut.set_result(None)
            except Exception as exc:  # noqa: BLE001
                fut.set_exception(exc)
            return fut

        executor = MagicMock()
        executor.submit.side_effect = _sync_submit
        svc._thread_executor = executor
        return svc, filetransfer

    def test_record_not_marked_when_transfer_fails(self, monkeypatch):
        import app.services.sync_service as mod

        svc, filetransfer = self._service(False, "????????")
        lock = MagicMock()
        lock.acquire.return_value = True
        monkeypatch.setattr(
            mod,
            "get_lock_manager",
            MagicMock(return_value=MagicMock(create_lock=MagicMock(return_value=lock))),
        )
        monkeypatch.setattr(os.path, "exists", lambda _p: True)

        svc.re_identify_items(flag="unidentification", ids=[670])

        filetransfer.update_transfer_unknown_state.assert_not_called()

    def test_record_marked_when_transfer_succeeds(self, monkeypatch):
        import app.services.sync_service as mod

        svc, filetransfer = self._service(True, "")
        lock = MagicMock()
        lock.acquire.return_value = True
        monkeypatch.setattr(
            mod,
            "get_lock_manager",
            MagicMock(return_value=MagicMock(create_lock=MagicMock(return_value=lock))),
        )
        monkeypatch.setattr(os.path, "exists", lambda _p: True)

        svc.re_identify_items(flag="unidentification", ids=[670])

        filetransfer.update_transfer_unknown_state.assert_called_once_with(
            "/media/gof/btstore/tv/x/S01E50.mkv"
        )
