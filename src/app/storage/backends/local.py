"""本地文件系统存储后端。"""

import errno
import os
import shutil
from collections.abc import Iterator
from typing import BinaryIO

import log
from app.storage.backends.base import FileInfo, StorageBackend, StorageConfig


class LocalStorageBackend(StorageBackend):
    """
    本地文件系统后端。

    直接替换 SystemUtils 的 copy/move/link/softlink，
    不再通过 subprocess 或外部命令。
    """

    def __init__(self, config: StorageConfig) -> None:
        super().__init__(config)

    def _resolve(self, path: str) -> str:
        return os.path.abspath(os.path.expanduser(path))

    def exists(self, path: str) -> bool:
        return os.path.exists(self._resolve(path))

    def stat(self, path: str) -> FileInfo | None:
        rp = self._resolve(path)
        if not os.path.exists(rp):
            return None
        st = os.stat(rp)
        return FileInfo(
            path=path,
            size=st.st_size,
            mtime=st.st_mtime,
            is_dir=os.path.isdir(rp),
        )

    def list_dir(self, path: str) -> Iterator[FileInfo]:
        rp = self._resolve(path)
        for entry in os.scandir(rp):
            st = entry.stat()
            yield FileInfo(
                path=entry.path,
                size=st.st_size if entry.is_file() else 0,
                mtime=st.st_mtime,
                ctime=st.st_ctime,
                is_dir=entry.is_dir(),
            )

    def read_stream(self, path: str) -> BinaryIO:
        return open(self._resolve(path), "rb")

    def write_stream(self, path: str, stream: BinaryIO, size: int = 0, chunk_size: int = 0) -> None:
        rp = self._resolve(path)
        os.makedirs(os.path.dirname(rp), exist_ok=True)
        # 使用 chunk_size 或默认 1MB 缓冲区，避免大文件拷贝时频繁小 IO
        length = chunk_size if chunk_size > 0 else 1024 * 1024
        with open(rp, "wb") as f:
            shutil.copyfileobj(stream, f, length=length)

    def mkdir(self, path: str, parents: bool = True) -> None:
        rp = self._resolve(path)
        if parents:
            os.makedirs(rp, exist_ok=True)
        else:
            os.mkdir(rp)

    def remove(self, path: str, recursive: bool = False) -> None:
        if not path or path in ("/", "\\"):
            raise ValueError("不能删除根目录")
        rp = self._resolve(path)
        # Unix: dirname('/') == '/'；Windows: dirname('E:\\') == 'E:\\'
        if not rp or os.path.dirname(rp) == rp:
            raise ValueError("不能删除根目录")
        if os.path.isdir(rp):
            if recursive:
                shutil.rmtree(rp)
            else:
                os.rmdir(rp)
        else:
            os.remove(rp)

    def copy(self, src: str, dst: str) -> None:
        src_rp = self._resolve(src)
        dst_rp = self._resolve(dst)
        os.makedirs(os.path.dirname(dst_rp), exist_ok=True)
        shutil.copy2(src_rp, dst_rp)

    def move(self, src: str, dst: str) -> None:
        src_rp = self._resolve(src)
        dst_rp = self._resolve(dst)
        os.makedirs(os.path.dirname(dst_rp), exist_ok=True)
        shutil.move(src_rp, dst_rp)

    def hardlink(self, src: str, dst: str) -> None:
        """硬链接；跨文件系统时自动降级为复制。

        硬链接只能在同一文件系统内建立。媒体库的「下载目录」与「媒体目录」
        经常分属不同磁盘（/media/storedisk1 ↔ /media/storedisk2 等），
        此时 os.link 会抛 EXDEV(18)。早期实现直接上抛，导致这批转移全部失败，
        文件既没进媒体库也没被清理，订阅侧还以为是重复下载。
        跨盘无法真正共享 inode，降级复制是唯一可行的行为。
        """
        src_rp = self._resolve(src)
        dst_rp = self._resolve(dst)
        os.makedirs(os.path.dirname(dst_rp), exist_ok=True)
        try:
            os.link(src_rp, dst_rp)
        except OSError as e:
            if e.errno != errno.EXDEV:
                raise
            log.warn(f"[Local]跨文件系统无法硬链接，降级为复制: {src_rp} -> {dst_rp}")
            shutil.copy2(src_rp, dst_rp)

    def softlink(self, src: str, dst: str) -> None:
        src_rp = self._resolve(src)
        dst_rp = self._resolve(dst)
        os.makedirs(os.path.dirname(dst_rp), exist_ok=True)
        os.symlink(src_rp, dst_rp)

    def health_check(self) -> tuple[bool, str]:
        return True, "本地文件系统"
