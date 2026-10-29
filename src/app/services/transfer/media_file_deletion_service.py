"""媒体文件删除服务：统一处理本地/远程存储后端的文件删除与路径校验."""

import os

import log
from app.core.constants import RMT_MEDIAEXT
from app.core.exceptions import ResourceNotFoundError, ServiceError, ValidationError
from app.db.repositories.storage_backend_repo_adapter import StorageBackendRepositoryAdapter
from app.storage import StorageBackendFactory
from app.storage.backends.base import StorageConfig, StorageType
from app.storage.backends.local import LocalStorageBackend
from app.storage.config_models import LocalStorageConfig
from app.utils import PathUtils


class MediaFileDeletionService:
    """负责单个媒体文件/目录的安全删除."""

    def __init__(
        self,
        path_resolver,
        storage_backend_repo: StorageBackendRepositoryAdapter | None = None,
    ):
        self._path_resolver = path_resolver
        self._storage_backend_repo = storage_backend_repo or StorageBackendRepositoryAdapter()

    def delete_media_file(self, filedir, filename, backend_id="local") -> None:
        """删除媒体文件（统一使用存储后端接口），失败时抛出异常."""
        file = os.path.join(filedir, filename).rstrip("/")
        filedir = os.path.dirname(file)
        filename = os.path.basename(file)

        if not filename:
            raise ValidationError("无效的文件路径")
        if not filedir or filedir in ("/", "\\"):
            raise ValidationError("不能删除根目录")
        if file == filedir:
            raise ValidationError("不能删除父目录")

        log.info(f"[Delete]准备删除：filedir={filedir}, filename={filename}, file={file}")

        backend = self.resolve_backend_by_id(backend_id)
        if not backend:
            raise ServiceError("无法解析存储后端")
        if not backend.exists(file):
            raise ResourceNotFoundError("文件不存在")

        backend.remove(file, recursive=True)
        log.info(f"[Delete]删除成功：{file}")

    def resolve_backend_by_id(self, backend_id: str):
        """根据 ID 解析存储后端（本地返回 LocalStorageBackend 实例）."""
        if not backend_id or backend_id == "local":
            return LocalStorageBackend(StorageConfig(id="local", name="local", type=StorageType.LOCAL))
        entity = self._storage_backend_repo.get_by_id(int(backend_id))
        if not entity:
            return None
        info = StorageBackendFactory.get_config_info(entity.type)
        if info:
            stype, cls = info
        else:
            stype, cls = StorageType.LOCAL, LocalStorageConfig
        config = cls(id=str(entity.id), name=entity.name, type=stype, enabled=entity.enabled)
        for key, value in entity.config.items():
            if hasattr(config, key):
                setattr(config, key, value)
        return StorageBackendFactory.create(config)

    def is_safe_delete_path(self, path: str, title: str | None = None) -> bool:
        """检查路径是否可以安全删除：必须在媒体库范围内且不是根目录."""
        if not path or path in ("/", "\\", "//"):
            return False
        if not self._path_resolver.is_target_dir_path(path):
            log.warn(f"[Delete]路径 {path} 不在媒体库范围内，跳过删除")
            return False
        if title and title not in path:
            log.warn(f"[Delete]路径 {path} 不包含媒体标题 {title}，跳过删除")
            return False
        return True

    def remove_dir_with_backend(self, path: str, backend_id: str = "local") -> None:
        """使用存储后端安全删除目录（支持 SMB/WebDAV 等远程存储）."""
        if not self.is_safe_delete_path(path):
            return
        backend = self.resolve_backend_by_id(backend_id)
        if not backend:
            log.error(f"[Delete]无法解析存储后端 {backend_id}")
            return
        if not backend.exists(path):
            log.warn(f"[Delete]路径不存在，跳过删除: {path}")
            return
        try:
            backend.remove(path, recursive=True)
            log.info(f"[Delete]目录删除成功: {path}")
        except Exception as exc:
            log.error(f"[Delete]删除目录失败 {path}: {exc}")
            raise

    def has_media_files(self, path: str, backend_id: str = "local") -> bool:
        """检查目录中是否还存在媒体文件，支持本地和远程存储."""
        if not path:
            return False
        if backend_id == "local":
            return bool(PathUtils.get_dir_files(in_path=path, exts=RMT_MEDIAEXT))
        backend = self.resolve_backend_by_id(backend_id)
        if not backend:
            return False
        try:
            for file_info in backend.list_dir(path):
                if not file_info.is_dir:
                    ext = os.path.splitext(file_info.path)[1].lower()
                    if ext in RMT_MEDIAEXT:
                        return True
            return False
        except Exception:
            return False
