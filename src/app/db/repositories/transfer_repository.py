"""
Transfer Repository
Handles transfer history and unrecognized transfer related database operations.
"""

import datetime
import os.path
import time
from enum import Enum

from sqlalchemy import func

from app.db.models import SYNCHISTORY, TRANSFERBLACKLIST, TRANSFERHISTORY, TRANSFERUNKNOWN
from app.db.repositories.base_repository import BaseRepository
from app.db.repositories.episode_progress import contiguous_episodes
from app.schemas.media import TransferMediaDTO
from app.utils.string_utils import StringUtils


class TransferRepository(BaseRepository):
    """
    转移历史仓储
    处理转移历史、未识别记录和黑名单的数据库操作
    """

    # ==================== Transfer History ====================

    def is_transfer_history_exists(
        self, source_path: str, source_filename: str, dest_path: str, dest_filename: str
    ) -> bool:
        """
        查询识别转移记录是否存在
        """
        if not source_path or not source_filename or not dest_path or not dest_filename:
            return False
        with self.session() as db:
            ret = (
                db.query(TRANSFERHISTORY)
                .filter(
                    source_path == TRANSFERHISTORY.SOURCE_PATH,
                    source_filename == TRANSFERHISTORY.SOURCE_FILENAME,
                    dest_path == TRANSFERHISTORY.DEST_PATH,
                    dest_filename == TRANSFERHISTORY.DEST_FILENAME,
                )
                .count()
            )
        return ret > 0

    def update_transfer_history_date(
        self, source_path: str, source_filename: str, dest_path: str, dest_filename: str, date: str
    ) -> None:
        """
        更新历史转移记录时间
        """
        with self.session() as db:
            db.query(TRANSFERHISTORY).filter(
                source_path == TRANSFERHISTORY.SOURCE_PATH,
                source_filename == TRANSFERHISTORY.SOURCE_FILENAME,
                dest_path == TRANSFERHISTORY.DEST_PATH,
                dest_filename == TRANSFERHISTORY.DEST_FILENAME,
            ).update({"DATE": date})

    def insert_transfer_history(
        self,
        in_from: Enum,
        rmt_mode: str,
        in_path: str,
        out_path: str,
        dest: str,
        media_info: TransferMediaDTO,
        dst_backend: str | None = None,
    ) -> None:
        """插入识别转移记录（单 session 原子操作，避免查-插竞态）。"""
        if not media_info:
            return

        if in_path:
            in_path = os.path.normpath(in_path)
            source_path = os.path.dirname(in_path)
            source_filename = os.path.basename(in_path)
        else:
            return

        if out_path:
            outpath = os.path.normpath(out_path)
            dest_path = os.path.dirname(outpath)
            dest_filename = os.path.basename(outpath)
            season_episode = media_info.season_episode
        else:
            dest_path = ""
            dest_filename = ""
            season_episode = media_info.season_episode

        title = media_info.title
        timestr = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))

        with self.session() as db:
            exists = (
                db.query(TRANSFERHISTORY)
                .filter(
                    TRANSFERHISTORY.SOURCE_PATH == source_path,
                    TRANSFERHISTORY.SOURCE_FILENAME == source_filename,
                    TRANSFERHISTORY.DEST_PATH == dest_path,
                    TRANSFERHISTORY.DEST_FILENAME == dest_filename,
                )
                .count()
            )
            if exists:
                db.query(TRANSFERHISTORY).filter(
                    TRANSFERHISTORY.SOURCE_PATH == source_path,
                    TRANSFERHISTORY.SOURCE_FILENAME == source_filename,
                    TRANSFERHISTORY.DEST_PATH == dest_path,
                    TRANSFERHISTORY.DEST_FILENAME == dest_filename,
                ).update({"DATE": timestr})
                return

            dest = dest or ""
            mode_value = rmt_mode or ""
            db.add(
                TRANSFERHISTORY(
                    MODE=mode_value,
                    TYPE=media_info.type_value,
                    CATEGORY=media_info.category,
                    TMDBID=int(media_info.tmdb_id),
                    TITLE=title,
                    YEAR=media_info.year,
                    SEASON_EPISODE=season_episode,
                    SOURCE=StringUtils.resolve_in_from_display(in_from),
                    SOURCE_PATH=source_path,
                    SOURCE_FILENAME=source_filename,
                    DEST=dest,
                    DEST_PATH=dest_path,
                    DEST_FILENAME=dest_filename,
                    DST_BACKEND=dst_backend or "local",
                    DATE=timestr,
                )
            )

    def get_transfer_history(self, search: str | None, page: int, rownum: int) -> tuple[int, list[TRANSFERHISTORY]]:
        """
        查询识别转移记录（分页）
        """
        if int(page) == 1:
            begin_pos = 0
        else:
            begin_pos = (int(page) - 1) * int(rownum)

        if search:
            search = f"%{search}%"
            with self.session() as db:
                count = (
                    db.query(TRANSFERHISTORY)
                    .filter((TRANSFERHISTORY.SOURCE_FILENAME.like(search)) | (TRANSFERHISTORY.TITLE.like(search)))
                    .count()
                )
                data = (
                    db.query(TRANSFERHISTORY)
                    .filter((TRANSFERHISTORY.SOURCE_FILENAME.like(search)) | (TRANSFERHISTORY.TITLE.like(search)))
                    .order_by(TRANSFERHISTORY.DATE.desc())
                    .limit(int(rownum))
                    .offset(begin_pos)
                    .all()
                )
                return count, data
        else:
            with self.session() as db:
                return db.query(TRANSFERHISTORY).count(), db.query(TRANSFERHISTORY).order_by(
                    TRANSFERHISTORY.DATE.desc()
                ).limit(int(rownum)).offset(begin_pos).all()

    def get_transfer_info_by_id(self, logid: int | None) -> TRANSFERHISTORY | None:
        """
        据logid查询PATH
        """
        with self.session() as db:
            return db.query(TRANSFERHISTORY).filter(int(logid or 0) == TRANSFERHISTORY.ID).first()

    def get_transfer_info_by(
        self, tmdbid: int | None, season: str | None = None, season_episode: str | None = None
    ) -> list[TRANSFERHISTORY] | None:
        """
        据tmdbid、season、season_episode查询转移记录
        """
        with self.session() as db:
            if tmdbid and not season and not season_episode:
                return db.query(TRANSFERHISTORY).filter(int(tmdbid) == TRANSFERHISTORY.TMDBID).all()
            if tmdbid and season:
                season = f"%{season}%"
                return (
                    db.query(TRANSFERHISTORY)
                    .filter(int(tmdbid) == TRANSFERHISTORY.TMDBID, TRANSFERHISTORY.SEASON_EPISODE.like(season))
                    .all()
                )
            if tmdbid and season_episode:
                return (
                    db.query(TRANSFERHISTORY)
                    .filter(int(tmdbid) == TRANSFERHISTORY.TMDBID, season_episode == TRANSFERHISTORY.SEASON_EPISODE)
                    .all()
                )
            return None

    def get_multi_version_groups(self, limit: int = 100) -> list[dict]:
        """
        统计同一 tmdb_id 下有多个不同文件（多版本/重复）的作品分组。

        以 TRANSFER_HISTORY 的实际落盘文件（DEST_FILENAME）为基础，
        同一作品（TMDBID）对应多个不同文件即视为存在多个版本/重复文件。
        仅返回版本数 > 1 的作品，避免全量遍历。
        注意：判断依据是"文件数>1"（同一目录内多个不同文件也算多版本），
        而非"目录数>1"——正片+花絮/不同规格常同目录存放。
        """
        if not limit or limit <= 0:
            limit = 100
        with self.session() as db:
            rows = (
                db.query(
                    TRANSFERHISTORY.TMDBID,
                    TRANSFERHISTORY.TITLE,
                    TRANSFERHISTORY.YEAR,
                    func.count(func.distinct(TRANSFERHISTORY.DEST_PATH)).label("dir_count"),
                    func.count(func.distinct(TRANSFERHISTORY.DEST_FILENAME)).label("file_count"),
                )
                .filter(TRANSFERHISTORY.TMDBID.isnot(None), TRANSFERHISTORY.TMDBID > 0)
                .group_by(TRANSFERHISTORY.TMDBID, TRANSFERHISTORY.TITLE, TRANSFERHISTORY.YEAR)
                .having(func.count(func.distinct(TRANSFERHISTORY.DEST_FILENAME)) > 1)
                .order_by(TRANSFERHISTORY.TITLE.asc())
                .limit(int(limit))
                .all()
            )
        return [{"tmdb_id": r[0], "title": r[1], "year": r[2], "dir_count": r[3], "file_count": r[4]} for r in rows]

    def get_transfer_logs_by_paths(self, paths: list[str]) -> list[TRANSFERHISTORY]:
        """按一组文件路径（源或目标）匹配所有转移记录。

        用于"按文件锚点清理"：给定硬链接链上的文件路径，找出涉及它们的全部转移记录
        （SOURCE_PATH/SOURCE_FILENAME 或 DEST_PATH/DEST_FILENAME 命中任一路径）。
        """
        if not paths:
            return []
        norm_paths = [os.path.normpath(p) for p in paths if p]
        if not norm_paths:
            return []
        with self.session() as db:
            return (
                db.query(TRANSFERHISTORY)
                .filter(
                    TRANSFERHISTORY.DEST_PATH.in_(norm_paths)
                    | TRANSFERHISTORY.DEST_FILENAME.in_([os.path.basename(p) for p in norm_paths])
                    | TRANSFERHISTORY.SOURCE_PATH.in_(norm_paths)
                    | TRANSFERHISTORY.SOURCE_FILENAME.in_([os.path.basename(p) for p in norm_paths])
                )
                .all()
            )

    def get_contiguous_transferred_episode_by_tmdb(self, tmdbid: int | None, season: int | None, start: int = 1) -> int:
        """
        查询某剧集某季已成功转移的「从订阅起点 start 起连续」的最大集号（重订阅续订用）。

        转移记录中的集数信息比下载记录可靠（下载记录 SE 可能为空）。
        解析逻辑见 episode_progress.contiguous_episodes。
        """
        if not tmdbid:
            return 0
        with self.session() as db:
            rows = db.query(TRANSFERHISTORY.SEASON_EPISODE).filter(int(tmdbid) == TRANSFERHISTORY.TMDBID).all()
        return contiguous_episodes((se for (se,) in rows), int(season or 1), start=int(start or 1))

    def delete_transfer_history_by_source(self, source_path: str, source_filename: str) -> None:
        with self.session() as db:
            db.query(TRANSFERHISTORY).filter(
                source_path == TRANSFERHISTORY.SOURCE_PATH,
                source_filename == TRANSFERHISTORY.SOURCE_FILENAME,
            ).delete()

    def is_transfer_history_exists_by_source_full_path(self, source_full_path: str) -> bool:
        """
        据源文件的全路径查询识别转移记录
        """
        path = os.path.dirname(source_full_path)
        filename = os.path.basename(source_full_path)
        with self.session() as db:
            return (
                db.query(TRANSFERHISTORY.ID)
                .filter(path == TRANSFERHISTORY.SOURCE_PATH, filename == TRANSFERHISTORY.SOURCE_FILENAME)
                .first()
                is not None
            )

    def delete_transfer_log_by_id(self, logid: int) -> None:
        """
        根据logid删除记录
        """
        with self.session() as db:
            db.query(TRANSFERHISTORY).filter(int(logid) == TRANSFERHISTORY.ID).delete()

    def update_transfer_dest(self, logid: int, new_dest_path: str, new_dest_filename: str) -> bool:
        """更新转移记录的目标路径（跨盘整理感知：记录 DEST 已手动移动后同步新位置）"""
        if not logid:
            return False
        with self.session() as db:
            row = db.query(TRANSFERHISTORY).filter(int(logid) == TRANSFERHISTORY.ID).first()
            if not row:
                return False
            row.DEST_PATH = new_dest_path
            row.DEST_FILENAME = new_dest_filename
            db.commit()
            return True

    def update_transfer_paths(
        self,
        logid: int,
        new_source_path: str,
        new_source_filename: str,
        new_dest_path: str,
        new_dest_filename: str,
    ) -> bool:
        """更新转移记录的源(SOURCE)与目标(DEST)路径（作品级跨盘归档迁移后同步新位置）"""
        if not logid:
            return False
        with self.session() as db:
            row = db.query(TRANSFERHISTORY).filter(int(logid) == TRANSFERHISTORY.ID).first()
            if not row:
                return False
            if new_source_path is not None:
                row.SOURCE_PATH = new_source_path
            if new_source_filename is not None:
                row.SOURCE_FILENAME = new_source_filename
            if new_dest_path is not None:
                row.DEST_PATH = new_dest_path
            if new_dest_filename is not None:
                row.DEST_FILENAME = new_dest_filename
            db.commit()
            return True

    def delete_transfer_logs(self, logids: list[int]) -> None:
        """
        批量删除识别记录
        """
        if not logids:
            return
        with self.session() as db:
            db.query(TRANSFERHISTORY).filter(TRANSFERHISTORY.ID.in_(logids)).delete()

    def delete_transfer(self) -> None:
        """
        删除所有识别记录
        """
        with self.session() as db:
            db.query(TRANSFERHISTORY).delete()

    def get_transfer_statistics(self, days: int = 30) -> list[tuple]:
        """
        查询历史记录统计
        使用 func.substring 替代 func.substr 以支持多种数据库
        days <= 0 表示查询全部
        """
        with self.session() as db:
            date_str = func.substr(TRANSFERHISTORY.DATE, 1, 10).label("date_str")
            query = db.query(TRANSFERHISTORY.TYPE, date_str, func.count("*"))
            if days > 0:
                begin_date = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
                query = query.filter(begin_date < TRANSFERHISTORY.DATE)
            return query.group_by(TRANSFERHISTORY.TYPE, date_str).order_by(date_str).all()

    # ==================== Transfer Unknown ====================

    def get_transfer_unknowns(self) -> list[TRANSFERUNKNOWN]:
        return self.get_transfer_unknown_paths()

    def get_transfer_unknown_paths(self) -> list[TRANSFERUNKNOWN]:
        """
        查询未识别的记录列表
        """
        with self.session() as db:
            return db.query(TRANSFERUNKNOWN).filter(TRANSFERUNKNOWN.STATE == "N").all()

    def get_transfer_unknown_paths_by_page(
        self, search: str | None, page: int, rownum: int
    ) -> tuple[int, list[TRANSFERUNKNOWN]]:
        """
        按页查询未识别的记录列表
        """
        if int(page) == 1:
            begin_pos = 0
        else:
            begin_pos = (int(page) - 1) * int(rownum)

        if search:
            search = f"%{search}%"
            with self.session() as db:
                count = (
                    db.query(TRANSFERUNKNOWN)
                    .filter((TRANSFERUNKNOWN.STATE == "N") & (TRANSFERUNKNOWN.PATH.like(search)))
                    .count()
                )
                data = (
                    db.query(TRANSFERUNKNOWN)
                    .filter((TRANSFERUNKNOWN.STATE == "N") & (TRANSFERUNKNOWN.PATH.like(search)))
                    .order_by(TRANSFERUNKNOWN.ID.desc())
                    .limit(int(rownum))
                    .offset(begin_pos)
                    .all()
                )
                return count, data
        else:
            with self.session() as db:
                return db.query(TRANSFERUNKNOWN).filter(TRANSFERUNKNOWN.STATE == "N").count(), db.query(
                    TRANSFERUNKNOWN
                ).filter(TRANSFERUNKNOWN.STATE == "N").order_by(TRANSFERUNKNOWN.ID.desc()).limit(int(rownum)).offset(
                    begin_pos
                ).all()

    def update_transfer_unknown_state(self, path: str) -> None:
        """
        更新未识别记录为识别
        """
        if not path:
            return
        with self.session() as db:
            db.query(TRANSFERUNKNOWN).filter(os.path.normpath(path) == TRANSFERUNKNOWN.PATH).update({"STATE": "Y"})

    def delete_transfer_unknowns(self, tids: list[int]) -> None:
        """
        批量删除未识别记录
        """
        if not tids:
            return
        with self.session() as db:
            db.query(TRANSFERUNKNOWN).filter(TRANSFERUNKNOWN.ID.in_(tids)).delete()

    def delete_transfer_unknown(self, tid: int | None) -> None:
        """
        删除未识别记录
        """
        if not tid:
            return
        self.delete_transfer_unknowns([tid])

    def get_transfer_unknown_by_id(self, tid: int | None) -> TRANSFERUNKNOWN | None:
        return self.get_unknown_info_by_id(tid)

    def get_unknown_info_by_id(self, tid: int | None) -> TRANSFERUNKNOWN | None:
        """
        查询未识别记录
        """
        if not tid:
            return None
        with self.session() as db:
            return db.query(TRANSFERUNKNOWN).filter(int(tid) == TRANSFERUNKNOWN.ID).first()

    def get_transfer_unknown_by_path(self, path: str) -> list[TRANSFERUNKNOWN]:
        """
        根据路径查询未识别记录
        """
        if not path:
            return []
        with self.session() as db:
            return db.query(TRANSFERUNKNOWN).filter(os.path.normpath(path) == TRANSFERUNKNOWN.PATH).all()

    def is_exists_transfer_unknowns(self, path: str) -> bool:
        return self.is_transfer_unknown_exists(path)

    def is_transfer_unknown_exists(self, path: str) -> bool:
        """
        查询未识别记录是否存在
        """
        if not path:
            return False
        with self.session() as db:
            ret = db.query(TRANSFERUNKNOWN).filter(os.path.normpath(path) == TRANSFERUNKNOWN.PATH).count()
        return ret > 0

    def is_need_insert_transfer_unknown(self, path: str) -> bool:
        """
        检查是否需要插入未识别记录
        """
        if not path:
            return False
        unknowns = self.get_transfer_unknown_by_path(path)
        if not unknowns:
            return True

        has_unprocessed = any(str(unknown.STATE or "") == "N" for unknown in unknowns)
        if has_unprocessed:
            return True

        if self.is_transfer_history_exists_by_source_full_path(path):
            return False

        # 批量删除已处理的无用未识别记录
        tids = [int(str(unknown.ID)) for unknown in unknowns if unknown.ID is not None]
        if tids:
            self.delete_transfer_unknowns(tids)
        return True

    def insert_transfer_unknown(self, path: str, dest: str, rmt_mode: str) -> None:
        """
        插入未识别记录
        """
        if not path:
            return
        if self.is_transfer_unknown_exists(path):
            return
        path = os.path.normpath(path)
        if dest:
            dest = os.path.normpath(dest)
        else:
            dest = ""
        with self.session() as db:
            db.add(TRANSFERUNKNOWN(PATH=path, DEST=dest, STATE="N", MODE=rmt_mode or ""))

    def is_transfer_in_blacklist(self, path: str) -> bool:
        """
        查询是否为黑名单
        """
        if not path:
            return False
        with self.session() as db:
            ret = db.query(TRANSFERBLACKLIST).filter(os.path.normpath(path) == TRANSFERBLACKLIST.PATH).count()
        return ret > 0

    def is_exists_transfer_blacklist(self, path: str) -> bool:
        return self.is_transfer_in_blacklist(path)

    def is_transfer_notin_blacklist(self, path: str) -> bool:
        """
        查询是否不在黑名单
        """
        return not self.is_transfer_in_blacklist(path)

    def truncate_transfer_unknowns(self) -> None:
        with self.session() as db:
            db.query(TRANSFERUNKNOWN).delete()

    def insert_transfer_blacklist(self, path: str) -> None:
        """
        插入黑名单记录（先去重，避免定时转移每分钟重复插入导致表膨胀）
        """
        if not path:
            return
        if self.is_transfer_in_blacklist(path):
            return
        with self.session() as db:
            db.add(TRANSFERBLACKLIST(PATH=os.path.normpath(path)))

    def delete_transfer_blacklist(self, path: str) -> None:
        """
        删除黑名单记录
        """
        with self.session() as db:
            db.query(TRANSFERBLACKLIST).filter(str(path) == TRANSFERBLACKLIST.PATH).delete()
            db.query(SYNCHISTORY).filter(str(path) == SYNCHISTORY.PATH).delete()

    def truncate_transfer_blacklist(self) -> None:
        """
        清空黑名单记录
        """
        with self.session() as db:
            db.query(TRANSFERBLACKLIST).delete()
            db.query(SYNCHISTORY).delete()

    # ==================== Sync History ====================

    def is_sync_in_history(self, path: str, dest: str) -> bool:
        """
        查询是否存在同步历史记录
        """
        if not path:
            return False
        with self.session() as db:
            return (
                db.query(SYNCHISTORY.ID)
                .filter(os.path.normpath(path) == SYNCHISTORY.PATH, os.path.normpath(dest) == SYNCHISTORY.DEST)
                .first()
                is not None
            )

    def insert_sync_history(self, path: str, src: str, dest: str) -> None:
        """
        插入同步历史记录
        """
        if not path or not dest:
            return
        if self.is_sync_in_history(path, dest):
            return

        with self.session() as db:
            db.add(SYNCHISTORY(PATH=os.path.normpath(path), SRC=os.path.normpath(src), DEST=os.path.normpath(dest)))
