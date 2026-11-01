"""私有插件 zip 包安全校验测试."""

import zipfile
from types import SimpleNamespace

import pytest

from app.plugin_framework.private_pack import (
    PrivatePackError,
    file_sha256,
    safe_extract,
    validate_private_manifest,
    validate_zip_members,
)


def test_validate_zip_rejects_path_traversal(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../evil.txt", "x")

    with zipfile.ZipFile(archive) as zf:
        with pytest.raises(PrivatePackError, match="非法 zip 路径"):
            validate_zip_members(zf)


def test_safe_extract_writes_normal_files(tmp_path):
    archive = tmp_path / "ok.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("manifest.json", "{}")
        zf.writestr("backend/plugin.py", "print('ok')")

    target = tmp_path / "out"
    safe_extract(str(archive), str(target))

    assert (target / "manifest.json").read_text() == "{}"
    assert (target / "backend/plugin.py").exists()
    assert file_sha256(str(archive))


def test_private_manifest_validation():
    def manifest(visibility="private", permission="metadata:private:view"):
        return SimpleNamespace(
            backend=SimpleNamespace(metadata=SimpleNamespace(visibility=visibility, required_permission=permission))
        )

    validate_private_manifest(manifest())

    with pytest.raises(PrivatePackError, match="visibility"):
        validate_private_manifest(manifest(visibility="public"))

    with pytest.raises(PrivatePackError, match="required_permission"):
        validate_private_manifest(manifest(permission=""))
