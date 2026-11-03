"""跨文件系统硬链接降级。

媒体库的下载目录与媒体目录经常分属不同磁盘，os.link 会抛 EXDEV(18)。
早期实现直接上抛，导致这批转移全部失败（文件既没进媒体库也没被清理）。
跨盘无法共享 inode，降级为复制是唯一可行的行为。
"""

import errno
import os

import pytest

from app.storage.backends.base import StorageConfig, StorageType
from app.storage.backends.local import LocalStorageBackend


@pytest.fixture
def backend():
    return LocalStorageBackend(StorageConfig(id="local", name="local", type=StorageType.LOCAL))


class TestHardlinkSameFilesystem:
    def test_creates_hardlink(self, backend, tmp_path):
        src = tmp_path / "a.mkv"
        src.write_bytes(b"payload")
        dst = tmp_path / "sub" / "b.mkv"

        backend.hardlink(str(src), str(dst))

        assert dst.read_bytes() == b"payload"
        # 同盘成功硬链接：inode 相同
        assert os.stat(src).st_ino == os.stat(dst).st_ino


class TestHardlinkCrossDevice:
    def test_falls_back_to_copy_on_exdev(self, backend, tmp_path, monkeypatch):
        src = tmp_path / "a.mkv"
        src.write_bytes(b"cross-device payload")
        dst = tmp_path / "out" / "b.mkv"

        def fake_link(a, b):
            raise OSError(errno.EXDEV, "Invalid cross-device link")

        monkeypatch.setattr(os, "link", fake_link)

        backend.hardlink(str(src), str(dst))

        # 降级为复制：内容一致，但不是同一个 inode
        assert dst.read_bytes() == b"cross-device payload"
        assert os.stat(src).st_ino != os.stat(dst).st_ino
        # 源文件保留（link 语义不消耗源），后续清理仍可处理
        assert src.exists()

    def test_creates_missing_parent_dir(self, backend, tmp_path, monkeypatch):
        src = tmp_path / "a.mkv"
        src.write_bytes(b"x")
        dst = tmp_path / "deep" / "nested" / "b.mkv"

        monkeypatch.setattr(os, "link", lambda a, b: (_ for _ in ()).throw(OSError(errno.EXDEV, "EXDEV")))

        backend.hardlink(str(src), str(dst))

        assert dst.exists()

    def test_preserves_mtime(self, backend, tmp_path, monkeypatch):
        src = tmp_path / "a.mkv"
        src.write_bytes(b"x")
        os.utime(src, (1_600_000_000, 1_600_000_000))
        dst = tmp_path / "b.mkv"

        monkeypatch.setattr(os, "link", lambda a, b: (_ for _ in ()).throw(OSError(errno.EXDEV, "EXDEV")))

        backend.hardlink(str(src), str(dst))

        # copy2 保留元数据，媒体库按 mtime 排序/去重依赖它
        assert int(os.stat(dst).st_mtime) == 1_600_000_000


class TestHardlinkOtherErrors:
    def test_other_oserror_propagates(self, backend, tmp_path, monkeypatch):
        src = tmp_path / "a.mkv"
        src.write_bytes(b"x")
        dst = tmp_path / "b.mkv"

        def fake_link(a, b):
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(os, "link", fake_link)

        # 只有 EXDEV 才降级；磁盘满等错误必须上抛，不能静默变成复制
        with pytest.raises(OSError) as ei:
            backend.hardlink(str(src), str(dst))
        assert ei.value.errno == errno.ENOSPC


class TestTransferEngineDegradation:
    """transfer_engine 的 link 操作应把 EXDEV 交给 backend 处理。"""

    def test_transfer_engine_link_cross_device(self, tmp_path, monkeypatch):
        from app.services.transfer_engine import TransferEngine

        src = tmp_path / "src.mkv"
        src.write_bytes(b"engine payload")
        dst = tmp_path / "dst.mkv"

        monkeypatch.setattr(os, "link", lambda a, b: (_ for _ in ()).throw(OSError(errno.EXDEV, "EXDEV")))

        TransferEngine()._execute(str(src), str(dst), "link")

        assert dst.read_bytes() == b"engine payload"
