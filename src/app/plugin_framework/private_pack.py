"""私有插件 zip 包校验与安全解压."""

from __future__ import annotations

import hashlib
import stat
import zipfile
from pathlib import Path, PurePosixPath

_MAX_MEMBER_SIZE = 64 * 1024 * 1024
_MAX_TOTAL_SIZE = 256 * 1024 * 1024


class PrivatePackError(ValueError):
    pass


def validate_zip_members(zf: zipfile.ZipFile) -> None:
    """拒绝路径穿越、绝对路径与符号链接."""
    total_size = 0
    for info in zf.infolist():
        if info.file_size > _MAX_MEMBER_SIZE:
            raise PrivatePackError(f"zip 单文件超过限制: {info.filename}")
        total_size += info.file_size
        if total_size > _MAX_TOTAL_SIZE:
            raise PrivatePackError("zip 解压后总大小超过限制")
        name = info.filename.replace("\\", "/")
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise PrivatePackError(f"非法 zip 路径: {name}")
        mode = info.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            raise PrivatePackError(f"zip 不允许符号链接: {name}")


def safe_extract(zip_path: str, extract_dir: str) -> None:
    """安全解压到目录."""
    target = Path(extract_dir).resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        validate_zip_members(zf)
        for info in zf.infolist():
            if info.is_dir():
                continue
            destination = (target / info.filename).resolve()
            if target not in destination.parents and destination != target:
                raise PrivatePackError(f"非法 zip 路径: {info.filename}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as source, destination.open("wb") as output:
                output.write(source.read())


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_private_manifest(manifest) -> None:
    """私有包必须声明 visibility=private 与访问权限."""
    metadata = getattr(getattr(manifest, "backend", None), "metadata", None)
    if metadata is None or getattr(metadata, "visibility", "public") != "private":
        raise PrivatePackError("私有插件包必须在 backend.metadata.visibility 声明 private")
    if not getattr(metadata, "required_permission", ""):
        raise PrivatePackError("私有插件包必须声明 required_permission")
