"""区分「本平台签发但已过期」与「无效/伪造凭证」。

access token 仅 15 分钟有效，前端收到 401 会自动刷新并重试，所以过期属
正常轮换，不该按安全事件告警；只有签名不匹配的凭证才是需要关注的问题。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from app.schemas.auth import UserContext
from app.services import auth_service as auth_mod
from app.services.auth_service import AuthService

# 伪造凭证用的密钥（长度需 >= 32 字节，避免 HS256 的 key 长度告警）
_FOREIGN_SECRET = "someone-elses-secret-key-0123456789abcdef"


def _ctx() -> UserContext:
    return UserContext(user_id=1, username="admin", nickname=None, level=0, permissions=[])


def _expired_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "exp": now - timedelta(minutes=1),
        "iat": now - timedelta(minutes=16),
        "type": "access",
        "user_id": 1,
        "username": "admin",
    }
    return jwt.encode(payload, auth_mod._SECRET_KEY, algorithm=auth_mod._ALGORITHM)


class TestIsTokenExpired:
    def test_valid_token_is_not_expired(self):
        pair = AuthService.create_token_pair(_ctx())
        assert AuthService.is_token_expired(pair.access_token) is False

    def test_expired_platform_token_is_expired(self):
        assert AuthService.is_token_expired(_expired_token()) is True

    def test_foreign_token_is_not_expired(self):
        """签名不匹配（伪造/其他平台签发）→ 不是「过期」，按无效凭证处理"""
        forged = jwt.encode(
            {"exp": datetime.now(timezone.utc) + timedelta(hours=1), "type": "access"},
            _FOREIGN_SECRET,
            algorithm="HS256",
        )
        assert AuthService.is_token_expired(forged) is False

    def test_garbage_token_is_not_expired(self):
        assert AuthService.is_token_expired("not-a-jwt") is False

    def test_empty_token_is_not_expired(self):
        assert AuthService.is_token_expired("") is False

    def test_expired_and_forged_is_not_expired(self):
        """既过期又签名不符 → 仍归为无效凭证，不享受「正常轮换」的降噪待遇"""
        forged_expired = jwt.encode(
            {"exp": datetime.now(timezone.utc) - timedelta(minutes=1), "type": "access"},
            _FOREIGN_SECRET,
            algorithm="HS256",
        )
        assert AuthService.is_token_expired(forged_expired) is False


class TestVerifyTokenStillRejectsExpired:
    def test_expired_token_still_rejected(self):
        """降噪只影响日志，认证结果仍必须是拒绝"""
        assert AuthService.verify_token(_expired_token()) is None

    def test_valid_token_accepted(self):
        pair = AuthService.create_token_pair(_ctx())
        ctx = AuthService.verify_token(pair.access_token)
        assert ctx is not None
        assert ctx.username == "admin"
