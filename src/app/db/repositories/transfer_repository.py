"""
Transfer Repository
Handles transfer history and unrecognized transfer related database operations.
"""

import datetime
import os.path
import time
from enum import Enum
from typing import Any

from sqlalchemy import and_, func, or_

from app.db.models import SYNCHISTORY, TRANSFERBLACKLIST, TRANSFERHISTORY, TRANSFERUNKNOWN
from app.db.repositories.base_repository import BaseRepository
from app.db.repositories.episode_progress import contiguous_episodes
from app.domain.mediatypes import MediaType
from app.schemas.media import TransferMediaDTO
from app.services.identity_resolver import IdentityResolver
from app.utils.string_utils import StringUtils


class TransferRepository(BaseRepository):
    """
    转移历史仓储
    处理转移历史、未识别记录和黑名单的数据库操作
    """

    def _identity_for_media(self, media_info: Any, title: str | None) -> str:
        return IdentityResolver().resolve_media(media_info, allow_local=True).identity_id

    def is_transfer_history_exists(
        self, source_path: str, source_filename: str, dest_path: str, dest_filename: str
    ) -> bool:
        """查询识别转移记录是否存在"""
        if not source_path or not source_filename or not dest_path or not dest_filename:
            return False
        with self.session() as db:
            ret = (
                db.query(TRANSFERHISTORY)
                .filter(
                    TRANSFERHISTORY.SOURCE_PATH == source_path,
                    TRANSFERHISTORY.SOURCE_FILENAME == source_filename,
                    TRANSFERHISTORY.DEST_PATH == dest_path,
                    TRANSFERHISTORY.DEST_FILENAME == dest_filename,
                )
                .count()
            )
        return ret > 0

    def update_transfer_history_date(
        self, source_path: str, source_filename: str, dest_path: str, dest_filename: str, date: str
    ) -> None:
        """更新历史转移记录时间"""
        with self.session() as db:
            db.query(TRANSFERHISTORY).filter(
                TRANSFERHISTORY.SOURCE_PATH == source_path,
                TRANSFERHISTORY.SOURCE_FILENAME == source_filename,
                TRANSFERHISTORY.DEST_PATH == dest_path,
                TRANSFERHISTORY.DEST_FILENAME == dest_filename,
            ).update({"DATE": date})

    def update_transfer_history_poster(self, logid: int | None, poster: str) -> None:
        """回填历史记录海报，后续列表直接读库，避免逐条回源."""
        if not logid or not poster:
            return
        with self.session() as db:
            db.query(TRANSFERHISTORY).filter(TRANSFERHISTORY.ID == logid).update({"POSTER": poster})

    def update_transfer_file_state(
        self,
        logid: int,
        *,
        source_state: str | None = None,
        source_deleted_at: str | None = None,
        dest_state: str | None = None,
        dest_deleted_at: str | None = None,
        files_checked_at: str | None = None,
    ) -> None:
        """更新记录关联文件的持久化状态，供历史列表直接读取."""
        values: dict[Any, Any] = {}
        if source_state is not None:
            values["SOURCE_STATE"] = source_state
        if source_deleted_at is not None:
            values["SOURCE_DELETED_AT"] = source_deleted_at
        if dest_state is not None:
            values["DEST_STATE"] = dest_state
        if dest_deleted_at is not None:
            values["DEST_DELETED_AT"] = dest_deleted_at
        if files_checked_at is not None:
            values["FILES_CHECKED_AT"] = files_checked_at
        if not values:
            return
        with self.session() as db:
            db.query(TRANSFERHISTORY).filter(TRANSFERHISTORY.ID == int(logid)).update(values)

    def update_retention_policy(self, logid: int, policy: str) -> bool:
        """设置单条记录的旧版本保留策略，返回是否命中记录."""
        if not logid:
            return False
        with self.session() as db:
            rows = (
                db.query(TRANSFERHISTORY)
                .filter(TRANSFERHISTORY.ID == int(logid))
                .update({"RETENTION_POLICY": str(policy)})
            )
            return bool(rows)

    def get_same_episode_records(self, record) -> list:
        """取与给定记录「同作品同季同集」的其它记录（用于洗版）.

        优先按 IDENTITY_ID 收敛；没有身份索引的旧数据退回 TMDBID + 季集匹配。
        只返回已入库且有目标路径的记录。
        """
        identity = str(getattr(record, "IDENTITY_ID", "") or "")
        tmdbid = str(getattr(record, "TMDBID", "") or "")
        season_episode = str(getattr(record, "SEASON_EPISODE", "") or "")
        with self.session() as db:
            query = db.query(TRANSFERHISTORY).filter(TRANSFERHISTORY.DEST_PATH != "")
            if identity:
                query = query.filter(TRANSFERHISTORY.IDENTITY_ID == identity)
            elif tmdbid:
                query = query.filter(TRANSFERHISTORY.TMDBID == tmdbid)
            else:
                return []
            rows = query.all()
        same: list = []
        for row in rows:
            if not str(getattr(row, "DEST_FILENAME", "") or ""):
                continue
            if season_episode and str(getattr(row, "SEASON_EPISODE", "") or "") != season_episode:
                continue
            same.append(row)
        return same

    def get_records_for_retention(self, limit: int = 2000) -> list:
        """保留策略对账的候选记录：有源路径与目标路径的最近记录."""
        with self.session() as db:
            return (
                db.query(TRANSFERHISTORY)
                .filter(TRANSFERHISTORY.SOURCE_PATH != "", TRANSFERHISTORY.DEST_FILENAME != "")
                .order_by(TRANSFERHISTORY.ID.desc())
                .limit(max(1, int(limit)))
                .all()
            )

    def get_replace_candidates(self) -> list:
        """policy=replace 且同集已存在更新记录的旧记录（洗版候选）."""
        with self.session() as db:
            olds = (
                db.query(TRANSFERHISTORY)
                .filter(
                    TRANSFERHISTORY.RETENTION_POLICY == "replace",
                    TRANSFERHISTORY.DEST_FILENAME != "",
                )
                .all()
            )
            if not olds:
                return []
            newer = (
                db.query(TRANSFERHISTORY)
                .filter(
                    TRANSFERHISTORY.DEST_FILENAME != "",
                    TRANSFERHISTORY.IDENTITY_ID.isnot(None),
                )
                .all()
            )
        latest: dict[tuple, int] = {}
        for row in newer:
            key = (
                str(getattr(row, "IDENTITY_ID", "") or ""),
                str(getattr(row, "SEASON_EPISODE", "") or ""),
            )
            latest[key] = max(latest.get(key, 0), int(getattr(row, "ID", 0) or 0))
        result: list = []
        for row in olds:
            key = (
                str(getattr(row, "IDENTITY_ID", "") or ""),
                str(getattr(row, "SEASON_EPISODE", "") or ""),
            )
            # 只有「同集已有更新的记录」才清理，避免把唯一版本删掉
            if latest.get(key, 0) > int(getattr(row, "ID", 0) or 0):
                result.append(row)
        return result

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
                    TMDBID=int(media_info.tmdb_id) if str(media_info.tmdb_id or "").isdigit() else 0,
                    TITLE=title,
                    YEAR=media_info.year,
                    SEASON_EPISODE=season_episode,
                    SOURCE=StringUtils.resolve_in_from_display(in_from),
                    SOURCE_PATH=source_path,
                    SOURCE_FILENAME=source_filename,
                    DEST=dest,
                    DEST_PATH=dest_path,
                    DEST_FILENAME=dest_filename,
                    POSTER=(media_info.poster or None),
                    DST_BACKEND=dst_backend or "local",
                    DATE=timestr,
                    IDENTITY_ID=self._identity_for_media(media_info, title),
                    SERIES_KEY=getattr(media_info, "series_key", None),
                    ANCHOR_PROVIDER=getattr(media_info, "anchor_provider", None),
                    ANCHOR_EXTERNAL_ID=getattr(media_info, "anchor_external_id", None),
                    CONTENT_PROFILE=getattr(media_info, "content_profile", None),
                    SOURCE_STATE="present",
                    DEST_STATE="present" if dest_filename else "unknown",
                )
            )

    def get_transfer_history(
        self, search: str | None, page: int, rownum: int, media_type: str | None = None
    ) -> tuple[int, list[TRANSFERHISTORY]]:
        """
        查询识别转移记录（分页）
        """
        if int(page) == 1:
            begin_pos = 0
        else:
            begin_pos = (int(page) - 1) * int(rownum)

        with self.session() as db:
            query = db.query(TRANSFERHISTORY)
            if search:
                pattern = f"%{search}%"
                query = query.filter(
                    (TRANSFERHISTORY.SOURCE_FILENAME.like(pattern)) | (TRANSFERHISTORY.TITLE.like(pattern))
                )
            if media_type:
                query = query.filter(TRANSFERHISTORY.TYPE == media_type)
            count = query.count()
            data = query.order_by(TRANSFERHISTORY.DATE.desc()).limit(int(rownum)).offset(begin_pos).all()
            return count, data

    def get_transfer_info_by_dest_path(self, dest_path: str, filename: str | None = None) -> list[TRANSFERHISTORY]:
        """按转移目标路径查询记录，供无 TMDB 的豆瓣/BGM 自动删除使用."""
        path = os.path.normpath(dest_path)
        name = str(filename or "").strip()
        with self.session() as db:
            if name:
                return (
                    db.query(TRANSFERHISTORY)
                    .filter(
                        TRANSFERHISTORY.DEST == os.path.dirname(path),
                        TRANSFERHISTORY.DEST_FILENAME == name,
                    )
                    .all()
                )
            exact = db.query(TRANSFERHISTORY).filter(TRANSFERHISTORY.DEST == path).all()
            if exact:
                return exact
            return db.query(TRANSFERHISTORY).filter(TRANSFERHISTORY.DEST.startswith(path.rstrip("/") + "/")).all()

    def get_existing_external_ids(self, external_ids: list[str]) -> set[str]:
        """按外部 ID 跨 provider 查询转移成功记录（订阅/转移 provider 可能不同）."""
        values = {str(item or "").strip() for item in external_ids if str(item or "").strip()}
        if not values:
            return set()
        with self.session() as db:
            rows = (
                db.query(TRANSFERHISTORY.ANCHOR_EXTERNAL_ID)
                .filter(TRANSFERHISTORY.ANCHOR_EXTERNAL_ID.in_(sorted(values)))
                .distinct()
                .all()
            )
        return {str(item[0] or "") for item in rows if item and item[0]}

    def get_existing_anchors(self, pairs: list[tuple[str, str]]) -> set[tuple[str, str]]:
        """批量查询已入库的内容锚点，供探索页标记使用."""
        normalized = {
            (str(provider).strip(), str(external).strip())
            for provider, external in pairs
            if str(provider or "").strip() and str(external or "").strip()
        }
        if not normalized:
            return set()
        conditions = [
            and_(
                TRANSFERHISTORY.ANCHOR_PROVIDER == provider,
                TRANSFERHISTORY.ANCHOR_EXTERNAL_ID == external,
            )
            for provider, external in normalized
        ]
        with self.session() as db:
            rows = (
                db.query(TRANSFERHISTORY.ANCHOR_PROVIDER, TRANSFERHISTORY.ANCHOR_EXTERNAL_ID)
                .filter(or_(*conditions))
                .all()
            )
        return {(str(provider), str(external)) for provider, external in rows}

    def get_existing_identity_ids(self, identity_ids: list[str]) -> set[str]:
        """批量查询已入库的媒体身份 ID，供探索页跨 provider 锚点兜底."""
        normalized = {str(item).strip() for item in identity_ids if str(item or "").strip()}
        if not normalized:
            return set()
        with self.session() as db:
            rows = (
                db.query(TRANSFERHISTORY.IDENTITY_ID)
                .filter(TRANSFERHISTORY.IDENTITY_ID.in_(list(normalized)))
                .distinct()
                .all()
            )
        return {str(row[0]) for row in rows if row[0]}

    def get_transfer_info_by_id(self, logid: int | None) -> TRANSFERHISTORY | None:
        """
        据logid查询PATH
        """
        with self.session() as db:
            return db.query(TRANSFERHISTORY).filter(TRANSFERHISTORY.ID == int(logid or 0)).first()

    def get_transfer_info_by(
        self, tmdbid: int | None, season: str | None = None, season_episode: str | None = None
    ) -> list[TRANSFERHISTORY] | None:
        """
        据tmdbid、season、season_episode查询转移记录
        """
        with self.session() as db:
            if tmdbid and not season and not season_episode:
                return db.query(TRANSFERHISTORY).filter(TRANSFERHISTORY.TMDBID == int(tmdbid)).all()
            if tmdbid and season:
                season = f"%{season}%"
                return (
                    db.query(TRANSFERHISTORY)
                    .filter(TRANSFERHISTORY.TMDBID == int(tmdbid), TRANSFERHISTORY.SEASON_EPISODE.like(season))
                    .all()
                )
            if tmdbid and season_episode:
                return (
                    db.query(TRANSFERHISTORY)
                    .filter(
                        TRANSFERHISTORY.TMDBID == int(tmdbid),
                        TRANSFERHISTORY.SEASON_EPISODE == season_episode,
                    )
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
        file_key = (
            func.coalesce(TRANSFERHISTORY.DEST_PATH, "") + "\0" + func.coalesce(TRANSFERHISTORY.DEST_FILENAME, "")
        )
        with self.session() as db:
            rows = (
                db.query(
                    TRANSFERHISTORY.TMDBID,
                    func.max(TRANSFERHISTORY.TITLE),
                    func.max(TRANSFERHISTORY.YEAR),
                    func.count(func.distinct(TRANSFERHISTORY.DEST_PATH)).label("dir_count"),
                    func.count(func.distinct(file_key)).label("file_count"),
                )
                .filter(TRANSFERHISTORY.TMDBID.isnot(None), TRANSFERHISTORY.TMDBID > 0)
                .group_by(TRANSFERHISTORY.TMDBID)
                .having(func.count(func.distinct(file_key)) > 1)
                .order_by(func.max(TRANSFERHISTORY.TITLE).asc())
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

    def get_transfer_info_by_ref(
        self,
        ref: str,
        season: str | None = None,
        season_episode: str | None = None,
        media_type: str | None = None,
    ) -> list[TRANSFERHISTORY] | None:
        """按统一引用查询转移记录；旧数字仅作为迁移兼容."""
        value = str(ref or "").strip()
        if not value:
            return None
        with self.session() as db:
            query = db.query(TRANSFERHISTORY)
            if value.startswith("id:"):
                query = query.filter(TRANSFERHISTORY.IDENTITY_ID == value[3:])
            elif ":" in value:
                provider, external = value.split(":", 1)
                query = query.filter(
                    TRANSFERHISTORY.ANCHOR_PROVIDER == provider,
                    TRANSFERHISTORY.ANCHOR_EXTERNAL_ID == external,
                )
            elif value.isdigit():
                query = query.filter(TRANSFERHISTORY.TMDBID == int(value))
            else:
                return None
            if media_type:
                # TMDB movie/tv 同号时用 TYPE 隔离；动漫历史可能落在 tv。
                types = {str(media_type)}
                if str(media_type) == "anime":
                    types.add("tv")
                query = query.filter(TRANSFERHISTORY.TYPE.in_(types))
            if season:
                query = query.filter(TRANSFERHISTORY.SEASON_EPISODE.like(f"%{season}%"))
            if season_episode:
                query = query.filter(TRANSFERHISTORY.SEASON_EPISODE == season_episode)
            return query.all()

    def get_contiguous_transferred_episode_by_tmdb(self, tmdbid: int | None, season: int | None, start: int = 1) -> int:
        """
        查询某剧集某季已成功转移的「从订阅起点 start 起连续」的最大集号（重订阅续订用）。

        转移记录中的集数信息比下载记录可靠（下载记录 SE 可能为空）。
        解析逻辑见 episode_progress.contiguous_episodes。
        """
        if not tmdbid:
            return 0
        with self.session() as db:
            rows = db.query(TRANSFERHISTORY.SEASON_EPISODE).filter(TRANSFERHISTORY.TMDBID == int(tmdbid)).all()
        return contiguous_episodes((se for (se,) in rows), int(season or 1), start=int(start or 1))

    def get_contiguous_transferred_episode_by_ref(
        self,
        ref: str,
        season: int | None,
        media_type: str | None = None,
        start: int = 1,
    ) -> int:
        """按统一引用查询该季连续已转移集数（非 TMDB 订阅续订用）."""
        if not str(ref or "").strip():
            return 0
        rows = (
            self.get_transfer_info_by_ref(
                ref,
                season=f"S{int(season or 1):02d}",
                media_type=media_type,
            )
            or []
        )
        return contiguous_episodes(
            (getattr(row, "SEASON_EPISODE", "") for row in rows),
            int(season or 1),
            start=int(start or 1),
        )

    def delete_transfer_history_by_source(self, source_path: str, source_filename: str) -> None:
        with self.session() as db:
            db.query(TRANSFERHISTORY).filter(
                TRANSFERHISTORY.SOURCE_PATH == source_path,
                TRANSFERHISTORY.SOURCE_FILENAME == source_filename,
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
                .filter(TRANSFERHISTORY.SOURCE_PATH == path, TRANSFERHISTORY.SOURCE_FILENAME == filename)
                .first()
                is not None
            )

    def get_transfer_history_by_source_full_path(self, source_full_path: str) -> TRANSFERHISTORY | None:
        """据源文件全路径取最近一条转移记录（用于校验目标是否仍存在）.

        兼容旧记录把完整文件路径写进 SOURCE_PATH 的格式。
        比较前把分隔符统一成 `/`：Windows 上 os.path.normpath 会把
        `/src/Movie/E01.mkv` 转成 `\\src\\Movie\\E01.mkv`，与库里存的原始字符串对不上。
        """
        normalized = os.path.normpath(source_full_path).replace("\\", "/")
        path = os.path.dirname(normalized)
        filename = os.path.basename(normalized)
        with self.session() as db:
            return (
                db.query(TRANSFERHISTORY)
                .filter(
                    (TRANSFERHISTORY.SOURCE_PATH == path) & (TRANSFERHISTORY.SOURCE_FILENAME == filename)
                    | (TRANSFERHISTORY.SOURCE_PATH == normalized)
                )
                .order_by(TRANSFERHISTORY.DATE.desc())
                .first()
            )

    def get_transfer_history_by_source_dir(self, source_dir: str) -> list[TRANSFERHISTORY]:
        """据源目录取该目录及其子目录下所有转移记录（用于校验目录目标是否仍存在）.

        目录同步批量传入的可能是种子目录（文件直接在其中），也可能是分类目录
        （媒体文件在更深的子目录下），故同时匹配目录本身与其后代。

        比较前把两侧分隔符统一成 `/`：Windows 上 os.path.normpath 会把
        `/src/Movie` 转成 `\\src\\Movie`，与库里存的原始字符串对不上。
        """
        if not source_dir:
            return []
        norm = os.path.normpath(source_dir).replace("\\", "/").rstrip("/")
        if not norm:
            return []
        col = func.replace(TRANSFERHISTORY.SOURCE_PATH, "\\", "/")
        prefix = norm + "/"
        with self.session() as db:
            return (
                db.query(TRANSFERHISTORY)
                .filter(or_(col == norm, col.startswith(prefix, autoescape=True)))
                .order_by(TRANSFERHISTORY.DATE.desc())
                .all()
            )

    def delete_transfer_log_by_id(self, logid: int) -> None:
        """
        根据logid删除记录
        """
        with self.session() as db:
            db.query(TRANSFERHISTORY).filter(TRANSFERHISTORY.ID == int(logid)).delete()

    def update_transfer_dest(self, logid: int, new_dest_path: str, new_dest_filename: str) -> bool:
        """更新转移记录的目标路径（跨盘整理感知：记录 DEST 已手动移动后同步新位置）"""
        if not logid:
            return False
        with self.session() as db:
            row = db.query(TRANSFERHISTORY).filter(TRANSFERHISTORY.ID == int(logid)).first()
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
            row = db.query(TRANSFERHISTORY).filter(TRANSFERHISTORY.ID == int(logid)).first()
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

    def get_transfer_statistics(self, days: int = 30) -> list:
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
                query = query.filter(TRANSFERHISTORY.DATE > begin_date)
            return query.group_by(TRANSFERHISTORY.TYPE, date_str).order_by(date_str).all()

    def get_transfer_series_statistics(self, days: int = 30) -> list:
        """
        按天统计电视剧去重剧数（distinct TMDBID，仅 tv 类型）
        返回 [(date_str, series_count), ...]
        """
        with self.session() as db:
            date_str = func.substr(TRANSFERHISTORY.DATE, 1, 10).label("date_str")
            query = db.query(date_str, func.count(func.distinct(TRANSFERHISTORY.TMDBID))).filter(
                TRANSFERHISTORY.TYPE == MediaType.TV.value,
                TRANSFERHISTORY.TMDBID > 0,
            )
            if days > 0:
                begin_date = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
                query = query.filter(TRANSFERHISTORY.DATE > begin_date)
            return query.group_by(date_str).order_by(date_str).all()

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
        norm = os.path.normpath(path)
        with self.session() as db:
            db.query(TRANSFERUNKNOWN).filter(
                or_(TRANSFERUNKNOWN.PATH == norm, TRANSFERUNKNOWN.PATH.like(f"{norm}/%"))
            ).update({"STATE": "Y"})

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
            return db.query(TRANSFERUNKNOWN).filter(TRANSFERUNKNOWN.ID == int(tid)).first()

    def get_transfer_unknown_by_path(self, path: str) -> list[TRANSFERUNKNOWN]:
        """
        根据路径查询未识别记录
        """
        if not path:
            return []
        with self.session() as db:
            return db.query(TRANSFERUNKNOWN).filter(TRANSFERUNKNOWN.PATH == os.path.normpath(path)).all()

    def is_exists_transfer_unknowns(self, path: str) -> bool:
        return self.is_transfer_unknown_exists(path)

    def is_transfer_unknown_exists(self, path: str) -> bool:
        """
        查询未识别记录是否存在
        """
        if not path:
            return False
        with self.session() as db:
            ret = db.query(TRANSFERUNKNOWN).filter(TRANSFERUNKNOWN.PATH == os.path.normpath(path)).count()
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
            ret = db.query(TRANSFERBLACKLIST).filter(TRANSFERBLACKLIST.PATH == os.path.normpath(path)).count()
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
            db.query(TRANSFERBLACKLIST).filter(TRANSFERBLACKLIST.PATH == str(path)).delete()
            db.query(SYNCHISTORY).filter(SYNCHISTORY.PATH == str(path)).delete()

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
                .filter(SYNCHISTORY.PATH == os.path.normpath(path), SYNCHISTORY.DEST == os.path.normpath(dest))
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

    def delete_sync_history(self, path: str, dest: str) -> None:
        """删除指定 (PATH, DEST) 的同步历史记录（目标文件被删除后用于重新同步）"""
        if not path or not dest:
            return
        with self.session() as db:
            db.query(SYNCHISTORY).filter(
                SYNCHISTORY.PATH == os.path.normpath(path),
                SYNCHISTORY.DEST == os.path.normpath(dest),
            ).delete(synchronize_session=False)

    def delete_sync_history_for_source(self, source_path: str) -> int:
        """按源路径清理同步历史，兼容文件与目录两种粒度。

        SYNCHISTORY.PATH 存的是**目录**（同步监听的单位），而识别记录里的
        SOURCE_PATH 可能是目录、SOURCE_FILENAME 才是文件名。早期清理只按
        「目录/文件」拼接的完整路径删除，目录级那条永远删不掉，
        于是「移除识别记录」后同步引擎仍判定已同步，内容再也无法重新入库。
        """
        text = str(source_path or "").strip()
        if not text:
            return 0
        normalized = os.path.normpath(text)
        with self.session() as db:
            rows = db.query(SYNCHISTORY).filter(SYNCHISTORY.PATH == normalized).delete(synchronize_session=False)
            # 目录下的子条目一并清理，避免残留历史继续拦住新文件
            prefix = normalized.rstrip("/") + "/"
            rows += (
                db.query(SYNCHISTORY)
                .filter(SYNCHISTORY.PATH.like(prefix + "%"))
                .delete(synchronize_session=False)
            )
            return int(rows)
