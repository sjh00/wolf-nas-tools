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
from app.core.error_codes import ErrorCode
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
    def test_expired_token_reports_token_expired_code(self, client):
        """过期 token → 401 且错误码为 TOKEN_EXPIRED（前端据此刷新）"""
        resp = client.get("/api/demo", headers={"Authorization": f"Bearer {_expired_access_token()}"})

        assert resp.status_code == 401
        assert resp.json()["code"] == ErrorCode.TOKEN_EXPIRED

    def test_expired_token_is_not_logged_as_warning(self, client):
        """正常过期属于预期流程，不应产生 WARNING 噪声"""
        with patch("api.exception_handlers.log") as mock_log:
            resp = client.get("/api/demo", headers={"Authorization": f"Bearer {_expired_access_token()}"})

        assert resp.status_code == 401
        mock_log.warn.assert_not_called()

    def test_invalid_token_reports_invalid_code(self, client):
        """伪造 token → 401 且错误码为 TOKEN_INVALID"""
        forged = jwt.encode(
            {"exp": datetime.now(timezone.utc) + timedelta(hours=1), "type": "access"},
            _FOREIGN_SECRET,
            algorithm="HS256",
        )
        resp = client.get("/api/demo", headers={"Authorization": f"Bearer {forged}"})

        assert resp.status_code == 401
        assert resp.json()["code"] == ErrorCode.TOKEN_INVALID
