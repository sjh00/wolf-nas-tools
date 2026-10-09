"""目录同步：目标硬链接被删除后应重新视为缺失，触发重新硬链接。

回归：`get_no_exists_medias` 的转移历史判断此前只看源文件是否存在，
目标媒体文件被删除后仍被当作“已转移”，导致同步不再硬链接。
"""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

from app.domain.mediatypes import MediaType
from app.services.transfer.filetransfer_service import FileTransferService


def _svc(exists: bool, tmp_path, dest_filename="E05.mkv"):
    src = tmp_path / "src.mkv"
    src.write_bytes(b"x")
    svc = FileTransferService.__new__(FileTransferService)
    svc._history = MagicMock()
    svc._existence = MagicMock()
    svc._history.get_transfer_info_by.return_value = [
        SimpleNamespace(
            source_path=str(src),
            season_episode="S01E05",
            dest_path=str(tmp_path / "lib"),
            dest_filename=dest_filename,
            dst_backend=None,
        )
    ]
    svc._existence.exists.return_value = exists
    svc._existence.get_no_exists_medias.return_value = [1, 2, 3]
    return svc


def _meta():
    return SimpleNamespace(type=MediaType.TV, tmdb_id=1)


def test_dest_exists_history_counts_transferred(tmp_path):
    svc = _svc(exists=True, tmp_path=tmp_path)
    result = svc.get_no_exists_medias(_meta(), season=1, total_num=12)
    assert set(result) == {1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12}
    cast(Any, svc._existence).get_no_exists_medias.assert_not_called()


def test_dest_deleted_falls_back_to_rescan(tmp_path):
    svc = _svc(exists=False, tmp_path=tmp_path)
    result = svc.get_no_exists_medias(_meta(), season=1, total_num=12)
    # 目标被删除 → 历史不计入 → 回退文件扫码（重新视为缺失）
    assert result == [1, 2, 3]
    cast(Any, svc._existence).get_no_exists_medias.assert_called_once()
