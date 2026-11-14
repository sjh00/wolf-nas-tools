"""批量自定义转移接口：多选文件必须逐个处理。

真实故障：文件管理里多选文件点「转移」只转了第一个（前端只发了 items[0]，
后端也只接受单个 inpath）。这里锁住后端侧的批量语义：
- inpaths 有多个 → 逐个调用转移，逐条返回结果
- 单条失败不影响其余
- 未传 inpaths → 行为与旧版完全一致（只处理 inpath）
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import get_current_user, get_sync_service
from api.routers import sync as sync_router
from app.schemas.auth import UserContext


@pytest.fixture
def mock_svc():
    svc = MagicMock()
    svc.build_media_type.return_value = None
    svc.remote_path_exists.return_value = True
    svc.manual_transfer.return_value = MagicMock(success=True, message="")
    return svc


@pytest.fixture
def client(mock_svc):
    app = FastAPI()
    app.include_router(sync_router.router, prefix="/api/v1/sync")
    admin = UserContext(
        user_id=1, username="admin", level=0, permissions=["setting:update"]
    )
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_sync_service] = lambda: mock_svc
    with TestClient(app) as test_client:
        yield test_client


def _post(client, payload):
    return client.post("/api/v1/sync/rename/udf", json=payload)


class TestBatchTransfer:
    def test_all_paths_are_transferred(self, client, mock_svc, tmp_path):
        """核心：三个路径必须调用三次转移，不能只处理第一个。"""
        paths = []
        for name in ("a.mkv", "b.mkv", "c.mkv"):
            item = tmp_path / name
            item.write_text("x", encoding="utf-8")
            paths.append(str(item))

        res = _post(client, {"inpaths": paths, "syncmod": "copy"})

        assert res.status_code == 200
        body = res.json()
        assert body["code"] == 0
        assert mock_svc.manual_transfer.call_count == 3
        transferred = [c.kwargs["inpath"] for c in mock_svc.manual_transfer.call_args_list]
        assert transferred == paths

    def test_per_path_results_returned(self, client, mock_svc, tmp_path):
        paths = []
        for name in ("a.mkv", "b.mkv"):
            item = tmp_path / name
            item.write_text("x", encoding="utf-8")
            paths.append(str(item))
        mock_svc.manual_transfer.side_effect = [
            MagicMock(success=True, message=""),
            MagicMock(success=False, message="识别失败"),
        ]

        body = _post(client, {"inpaths": paths, "syncmod": "copy"}).json()
        data = body["data"]

        assert data["total"] == 2
        assert data["succeeded"] == 1
        assert data["failed"] == 1
        assert [r["success"] for r in data["results"]] == [True, False]
        assert data["results"][1]["message"] == "识别失败"

    def test_partial_failure_still_succeeds(self, client, mock_svc, tmp_path):
        """部分成功时整体算成功（详情在 data 里），前端据此提示成功数与失败项。"""
        paths = []
        for name in ("a.mkv", "b.mkv"):
            item = tmp_path / name
            item.write_text("x", encoding="utf-8")
            paths.append(str(item))
        mock_svc.manual_transfer.side_effect = [
            MagicMock(success=True, message=""),
            MagicMock(success=False, message="boom"),
        ]

        body = _post(client, {"inpaths": paths, "syncmod": "copy"}).json()

        assert body["code"] == 0
        assert "1" in body["message"]

    def test_all_failure_returns_error_code(self, client, mock_svc, tmp_path):
        item = tmp_path / "a.mkv"
        item.write_text("x", encoding="utf-8")
        mock_svc.manual_transfer.return_value = MagicMock(
            success=False, message="识别失败"
        )

        body = _post(client, {"inpaths": [str(item)], "syncmod": "copy"}).json()

        assert body["code"] != 0
        assert body["data"]["succeeded"] == 0

    def test_missing_path_reported_per_item(self, client, mock_svc, tmp_path):
        """不存在的路径只让该条失败，不拖垮整批。"""
        good = tmp_path / "ok.mkv"
        good.write_text("x", encoding="utf-8")

        body = _post(
            client,
            {"inpaths": [str(good), str(tmp_path / "missing.mkv")], "syncmod": "copy"},
        ).json()

        data = body["data"]
        assert data["succeeded"] == 1
        assert data["failed"] == 1
        assert mock_svc.manual_transfer.call_count == 1

    def test_empty_inpaths_rejected(self, client, mock_svc):
        body = _post(client, {"inpaths": [], "syncmod": "copy"}).json()

        assert body["code"] != 0
        mock_svc.manual_transfer.assert_not_called()

    def test_blank_paths_are_ignored(self, client, mock_svc, tmp_path):
        item = tmp_path / "a.mkv"
        item.write_text("x", encoding="utf-8")

        body = _post(
            client, {"inpaths": [str(item), "", "   "], "syncmod": "copy"}
        ).json()

        assert body["data"]["total"] == 1
        assert mock_svc.manual_transfer.call_count == 1


class TestSingleModeUnchanged:
    def test_inpath_still_works_without_inpaths(self, client, mock_svc, tmp_path):
        """旧调用方只传 inpath，行为必须与改动前一致。"""
        item = tmp_path / "a.mkv"
        item.write_text("x", encoding="utf-8")

        body = _post(client, {"inpath": str(item), "syncmod": "copy"}).json()

        assert body["code"] == 0
        assert body["message"] == "转移成功"
        mock_svc.manual_transfer.assert_called_once()
        assert mock_svc.manual_transfer.call_args.kwargs["inpath"] == str(item)

    def test_single_missing_path_fails_whole_request(self, client, mock_svc, tmp_path):
        body = _post(
            client, {"inpath": str(tmp_path / "nope.mkv"), "syncmod": "copy"}
        ).json()

        assert body["code"] != 0
        mock_svc.manual_transfer.assert_not_called()
