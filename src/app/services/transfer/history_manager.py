"""TransferHistoryManager - 转移历史记录 CRUD 管理."""

import os

from app.db.repositories.download_repo_adapter import DownloadHistoryRepositoryAdapter
from app.db.repositories.transfer_repo_adapter import (
    TransferBlacklistRepositoryAdapter,
    TransferHistoryRepositoryAdapter,
    TransferUnknownRepositoryAdapter,
)
from app.domain.interfaces.download_repo import IDownloadHistoryRepository
from app.domain.interfaces.transfer_repo import (
    ITransferBlacklistRepository,
    ITransferHistoryRepository,
    ITransferUnknownRepository,
)
from app.schemas.media import TransferMediaDTO


class TransferHistoryManager:
    """负责转移历史记录、未知记录、黑名单的查询与修改."""

    def __init__(
        self,
        transfer_repo: ITransferHistoryRepository | None = None,
        transfer_blacklist_repo: ITransferBlacklistRepository | None = None,
        transfer_unknown_repo: ITransferUnknownRepository | None = None,
        download_repo: IDownloadHistoryRepository | None = None,
    ):
        self.transfer_repo = transfer_repo or TransferHistoryRepositoryAdapter()
        self.transfer_blacklist_repo = transfer_blacklist_repo or TransferBlacklistRepositoryAdapter()
        self.transfer_unknown_repo = transfer_unknown_repo or TransferUnknownRepositoryAdapter()
        self.download_repo = download_repo or DownloadHistoryRepositoryAdapter()

    # ---------- 下载记录 ----------

    def lookup_download_record(self, in_path):
        """根据路径查找下载记录中的媒体信息."""
        download_info = self.download_repo.get_download_history_by_path(in_path)
        if not download_info and os.path.isfile(in_path):
            download_info = self.download_repo.get_download_history_by_path(os.path.dirname(in_path))
        if download_info and str(download_info.TMDBID or ""):
            return download_info.TMDBID, download_info.TYPE
        return None, None

    # ---------- 转移历史 ----------

    def get_transfer_info_by(self, tmdbid, season=None, season_episode=None):
        return self.transfer_repo.get_transfer_info_by(tmdbid=tmdbid, season=season, season_episode=season_episode)

    def get_multi_version_groups(self, limit: int = 100):
        """统计同一作品存在多个版本/重复文件的作品列表"""
        return self.transfer_repo.get_multi_version_groups(limit=limit)

    def get_transfer_logs_by_paths(self, paths: list[str]):
        """按一组文件路径（源或目标）匹配全部转移记录（按文件锚点清理用）"""
        return self.transfer_repo.get_transfer_logs_by_paths(paths=paths)

    def get_contiguous_transferred_episode_by_tmdb(self, tmdbid, season: int | None = None, start: int = 1) -> int:
        """查询某季已成功转移的连续集数（重订阅续订用，季包保守记 start）."""
        return self.transfer_repo.get_contiguous_transferred_episode_by_tmdb(tmdbid=tmdbid, season=season, start=start)

    def get_transfer_info_by_id(self, logid):
        return self.transfer_repo.get_transfer_info_by_id(logid=logid)

    def get_transfer_history(self, search, page, rownum):
        return self.transfer_repo.get_transfer_history(search=search, page=page, rownum=rownum)

    def delete_transfer_log_by_id(self, logid):
        return self.transfer_repo.delete_transfer_log_by_id(logid=logid)

    def update_transfer_dest(self, logid, new_dest_path, new_dest_filename):
        """更新转移记录目标路径（跨盘整理感知）"""
        return self.transfer_repo.update_transfer_dest(
            logid=logid, new_dest_path=new_dest_path, new_dest_filename=new_dest_filename
        )

    def update_transfer_paths(self, logid, new_source_path, new_source_filename, new_dest_path, new_dest_filename):
        """更新转移记录源(SOURCE)与目标(DEST)路径（作品级跨盘归档迁移后同步）"""
        return self.transfer_repo.update_transfer_paths(
            logid=logid,
            new_source_path=new_source_path,
            new_source_filename=new_source_filename,
            new_dest_path=new_dest_path,
            new_dest_filename=new_dest_filename,
        )

    def delete_transfer_logs(self, logids: list[int]) -> None:
        return self.transfer_repo.delete_transfer_logs(logids=logids)

    def delete_transfer(self):
        return self.transfer_repo.delete_transfer()

    def get_transfer_statistics(self, days=30):
        return self.transfer_repo.get_transfer_statistics(days=days)

    # ---------- 未知记录 ----------

    def delete_transfer_unknown(self, tid):
        return self.transfer_repo.delete_transfer_unknown(tid=tid)

    def delete_transfer_unknowns(self, tids: list[int]) -> None:
        return self.transfer_repo.delete_transfer_unknowns(tids=tids)

    def get_unknown_info_by_id(self, tid):
        return self.transfer_repo.get_unknown_info_by_id(tid=tid)

    def update_transfer_unknown_state(self, path):
        return self.transfer_repo.update_transfer_unknown_state(path=path)

    def get_transfer_unknown_paths(self):
        return self.transfer_repo.get_transfer_unknown_paths()

    def is_transfer_unknown_exists(self, reg_path):
        return self.transfer_repo.is_transfer_unknown_exists(reg_path)

    def get_transfer_unknown_paths_by_page(self, search, page, rownum):
        return self.transfer_repo.get_transfer_unknown_paths_by_page(search=search, page=page, rownum=rownum)

    def is_need_insert_transfer_unknown(self, reg_path):
        return self.transfer_repo.is_need_insert_transfer_unknown(reg_path)

    def insert_transfer_unknown(self, reg_path, target_dir, operation):
        return self.transfer_repo.insert_transfer_unknown(reg_path, target_dir, operation)

    # ---------- 黑名单 ----------

    def insert_transfer_blacklist(self, path):
        return self.transfer_blacklist_repo.insert(path)

    def delete_transfer_blacklist(self, path):
        return self.transfer_repo.delete_transfer_blacklist(path=path)

    def truncate_transfer_blacklist(self):
        return self.transfer_repo.truncate_transfer_blacklist()

    def is_transfer_notin_blacklist(self, file_path):
        return self.transfer_repo.is_transfer_notin_blacklist(file_path)

    # ---------- 写入历史 ----------

    def insert_transfer_history(
        self, in_from, rmt_mode, in_path, out_path, dest, media_info: TransferMediaDTO, dst_backend
    ):
        return self.transfer_repo.insert_transfer_history(
            in_from=in_from,
            rmt_mode=rmt_mode,
            in_path=in_path,
            out_path=out_path,
            dest=dest,
            media_info=media_info,
            dst_backend=dst_backend,
        )
