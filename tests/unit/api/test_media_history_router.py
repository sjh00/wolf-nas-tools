"""识别历史记录/文件操作接口测试."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import (
    get_current_user,
    get_filetransfer_service,
    get_transfer_history_service,
)
from api.routers import media as media_router
from app.schemas.auth import UserContext


@pytest.fixture
def mock_history_service():
    return MagicMock()


@pytest.fixture
def mock_filetransfer_service():
    ft = MagicMock()
    ft.delete_records.return_value = [
        {"id": 1, "status": "deleted", "message": ""},
        {"id": 2, "status": "skipped", "message": "记录不存在"},
    ]
    ft.delete_record_files.return_value = [
        {"id": 1, "target": "source", "status": "deleted", "state": "deleted", "message": ""}
    ]
    ft.check_record_files.return_value = [
        {"id": 1, "target": "source", "state": "present", "message": ""},
        {"id": 1, "target": "library", "state": "deleted", "message": ""},
    ]
    return ft


@pytest.fixture
def client(mock_history_service, mock_filetransfer_service):
    app = FastAPI()
    app.include_router(media_router.router, prefix="/api/v1/media")
    admin_ctx = UserContext(
        user_id=1,
        username="admin",
        level=0,
        permissions=["library:manage", "transfer:view"],
    )
    app.dependency_overrides[get_current_user] = lambda: admin_ctx
    app.dependency_overrides[get_transfer_history_service] = lambda: mock_history_service
    app.dependency_overrides[get_filetransfer_service] = lambda: mock_filetransfer_service
    with TestClient(app) as test_client:
        yield test_client


class TestMediaHistoryRouter:
    def test_delete_records(self, client, mock_history_service, mock_filetransfer_service):
        response = client.post("/api/v1/media/history/records/delete", json={"ids": [1, 2]})

        assert response.status_code == 200
        assert response.json()["code"] == 0
        data = response.json()["data"]
        assert data["deleted"] == 1
        assert data["total"] == 2
        mock_filetransfer_service.delete_records.assert_called_once_with([1, 2])
        mock_history_service.invalidate_cache.assert_called_once()

    def test_delete_records_requires_ids(self, client, mock_filetransfer_service):
        response = client.post("/api/v1/media/history/records/delete", json={"ids": []})

        assert response.status_code == 200
        assert response.json()["code"] != 0
        mock_filetransfer_service.delete_records.assert_not_called()

    def test_delete_files(self, client, mock_history_service, mock_filetransfer_service):
        response = client.post(
            "/api/v1/media/history/files/delete",
            json={"ids": [1], "targets": ["source"]},
        )

        assert response.status_code == 200
        assert response.json()["code"] == 0
        mock_filetransfer_service.delete_record_files.assert_called_once_with([1], ["source"])
        mock_history_service.invalidate_cache.assert_called_once()

    def test_delete_files_rejects_unknown_target(self, client, mock_filetransfer_service):
        response = client.post(
            "/api/v1/media/history/files/delete",
            json={"ids": [1], "targets": ["all"]},
        )

        assert response.status_code == 200
        assert response.json()["code"] != 0
        mock_filetransfer_service.delete_record_files.assert_not_called()

    def test_check_files(self, client, mock_history_service, mock_filetransfer_service):
        response = client.post("/api/v1/media/history/files/check", json={"ids": [1]})

        assert response.status_code == 200
        assert response.json()["code"] == 0
        assert len(response.json()["data"]["results"]) == 2
        mock_filetransfer_service.check_record_files.assert_called_once_with([1], None)
