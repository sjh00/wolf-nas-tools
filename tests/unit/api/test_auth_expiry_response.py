"""过期 token 的 401 响应应可被识别，便于前端自动刷新与日志降噪。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.deps import get_current_user
from api.exception_handlers import register_exception_handlers
from app.services import auth_service as auth_mod

_FOREIGN_SECRET = "someone-elses-secret-key-0123456789abcdef"


@pytest.fixture
def client():
    app = FastAPI()
    register_exception_handlers(app)
    ctx = MagicMock()
    # 让 API Key 分支明确判定失败，从而走到 JWT/凭证兜底逻辑
    ctx.apikey_service.validate_key.return_value = None
    app.state.context = ctx

    @app.get("/api/demo")
    def demo(user: object = Depends(get_current_user)):  # noqa: B008
        return {"code": 0, "data": "ok", "message": ""}

    with TestClient(app) as c:
        yield c


def _expired_access_token() -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "exp": now - timedelta(minutes=1),
            "iat": now - timedelta(minutes=16),
            "type": "access",
            "user_id": 1,
            "username": "admin",
            "permissions": [],
        },
        auth_mod._SECRET_KEY,
        algorithm=auth_mod._ALGORITHM,
    )


class TestExpiredTokenResponse:
    def test_expired_token_marks_details_expired(self, client):
        """过期 token → 401 且 details.expired=True"""
        resp = client.get("/api/demo", headers={"Authorization": f"Bearer {_expired_access_token()}"})

        assert resp.status_code == 401
        assert resp.json()["details"].get("expired") is True

    def test_invalid_token_does_not_mark_expired(self, client):
        """伪造 token → 401 但不带 expired 标记（按安全事件处理）"""
        forged = jwt.encode(
            {"exp": datetime.now(timezone.utc) + timedelta(hours=1), "type": "access"},
            _FOREIGN_SECRET,
            algorithm="HS256",
        )
        resp = client.get("/api/demo", headers={"Authorization": f"Bearer {forged}"})

        assert resp.status_code == 401
        assert not (resp.json().get("details") or {}).get("expired")

    def test_missing_credentials_not_marked_expired(self, client):
        """完全没带凭证 → 401 但不带 expired 标记"""
        resp = client.get("/api/demo")

        assert resp.status_code == 401
        assert not (resp.json().get("details") or {}).get("expired")

    def test_expiry_is_logged_at_debug_not_warn(self, client):
        """过期属正常轮换，应降为 debug，避免每 15 分钟刷一条告警"""
        with patch("api.exception_handlers.log") as mock_log:
            resp = client.get("/api/demo", headers={"Authorization": f"Bearer {_expired_access_token()}"})

        assert resp.status_code == 401
        mock_log.warn.assert_not_called()
        mock_log.debug.assert_called_once()

    def test_invalid_credentials_still_warn(self, client):
        """无效凭证仍需告警（安全审计）"""
        with patch("api.exception_handlers.log") as mock_log:
            resp = client.get("/api/demo", headers={"Authorization": "Bearer not-a-jwt"})

        assert resp.status_code == 401
        mock_log.warn.assert_called_once()
