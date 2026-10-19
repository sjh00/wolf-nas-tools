"""批量重命名使用的存储后端解析与路径工具."""

from __future__ import annotations

import os
from typing import Any

import log
from app.storage import LocalStorageBackend, StorageBackendFactory
from app.storage.backends.base import StorageBackend, StorageType
from app.storage.config_models import LocalStorageConfig


def normalize_backend(backend_id: Any) -> str:
    value = str(backend_id or "local").strip()
    return "local" if value.lower() in ("", "local", "none", "0") else value


def resolve_backend(storage_repo, backend_id: Any) -> StorageBackend | None:
    normalized = normalize_backend(backend_id)
    if normalized == "local":
        return LocalStorageBackend(LocalStorageConfig(id="local", name="本地", type=StorageType.LOCAL))
    try:
        entity = storage_repo.get_by_id(int(normalized))
    except (TypeError, ValueError):
        return None
    if not entity or not entity.enabled:
        return None
    info = StorageBackendFactory.get_config_info(entity.type)
    stype, cls = info if info else (StorageType.LOCAL, LocalStorageConfig)
    config = cls(id=str(entity.id), name=entity.name, type=stype, enabled=entity.enabled)
    for key, value in (entity.config or {}).items():
        if hasattr(config, key):
            setattr(config, key, value)
    try:
        return StorageBackendFactory.create(config)
    except Exception as e:  # noqa: BLE001
        log.warn(f"[LibraryRename]创建存储后端失败 {backend_id}: {e}")
        return None


def norm_path(path: str) -> str:
    return os.path.normpath(str(path or "").replace("\\", "/"))


def dirname(path: str) -> str:
    return os.path.dirname(norm_path(path))


def basename(path: str) -> str:
    return os.path.basename(norm_path(path))


def target_dir_lock_key(backend_id: Any, directory: str) -> str:
    """所有写入媒体库的组件共享的目标目录锁 key."""
    return f"library:target:dir:{normalize_backend(backend_id)}:{norm_path(directory)}"
