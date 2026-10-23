"""媒体路由私有来源访问范围测试."""

from types import SimpleNamespace

from api.routers.media import _private_scope


def test_superadmin_skips_explicit_permission_code():
    """超管没有显式 metadata:private:view 权限码也应访问私有来源."""
    user = SimpleNamespace(is_superadmin=True, permissions=[])

    allow_private, permissions = _private_scope(user)

    assert allow_private is True
    assert permissions is None


def test_user_with_private_permission_keeps_permission_set():
    user = SimpleNamespace(is_superadmin=False, permissions=["metadata:private:view"])

    allow_private, permissions = _private_scope(user)

    assert allow_private is True
    assert permissions == {"metadata:private:view"}


def test_user_without_private_permission_denied():
    user = SimpleNamespace(is_superadmin=False, permissions=["library:view"])

    allow_private, permissions = _private_scope(user)

    assert allow_private is False
    assert permissions == {"library:view"}
