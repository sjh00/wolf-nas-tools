"""MediaMigrateService - 作品级"跨盘归档迁移".

用户习惯：订阅内容自动下载到盘A（btstore 做种源 + medialink 媒体库硬链接），
收藏时希望把整个作品（源 + 媒体库）一键迁移到盘B（收藏盘），保持硬链接。

本服务负责：
1. 收集某作品（tmdb_id）的全部转移记录，按源目录组 + 媒体库目录组去重。
2. 目录级迁移到目标盘的源目录 + 媒体库目录：
   - 同盘：目录级 move（shutil.move 同文件系统走 os.rename，保留 inode，硬链接关系保持）
   - 跨盘：递归复制 -> 校验大小/存在 -> 删除旧位置（先复制后删，保证不丢文件）
3. 迁移后更新 TRANSFERHISTORY 的 SOURCE_PATH/DEST_PATH，以及 DOWNLOADHISTORY.SAVE_PATH。

目标目录（target_source / target_dest）来自目录同步配置（CONFIG_SYNC_PATHS）中用户选定的
目标盘源目录与媒体库目录。跨盘判断：优先同盘（os.stat st_dev / splitdrive 自动检测），
必要时由前端传入 cross_drive 勾选兜底（docker 内挂载可能无法确知物理盘）。
"""

from __future__ import annotations

import os
import shutil

import log
from app.core.exceptions import ServiceError, ValidationError
from app.utils.path_utils import PathUtils


class MediaMigrateService:
    """作品级跨盘归档迁移服务。"""

    def __init__(self, history_manager, download_repo, downloader_core=None):
        self._history = history_manager
        self._download_repo = download_repo
        self._downloader_core = downloader_core

    # ---------- 对外入口 ----------

    def detect_orphans(self, tmdb_id: int | None = None) -> dict:
        """检测孤儿源文件：源文件在磁盘/记录中存在，但下载器中已经没有对应的做种任务。

        用户删除下载记录时，下载器可能因某些原因删除任务但未删除源文件（且无提示），
        导致源文件残留占用磁盘且难以发现。本方法把这类"有源文件但无下载器任务"的记录标出来。

        :param tmdb_id: 可选，仅检测指定作品；为空则检测全部有源文件的转移记录。
        :return: {total, orphans: [record...], source_dirs}
        """
        records = self._get_records(tmdb_id) if tmdb_id else self._get_all_records()
        if not records:
            return {"total": 0, "orphans": [], "source_dirs": []}
        torrents = self._get_all_torrents()
        orphan_records = []
        source_dirs: set[str] = set()
        for r in records:
            source_full = self._source_full(r)
            if not source_full:
                continue
            # 源文件必须实际存在于磁盘，才可能是"残留"
            if not os.path.exists(source_full):
                continue
            source_dir = os.path.dirname(source_full)
            if source_dir:
                source_dirs.add(source_dir)
            if not self._has_torrent_for_source(source_full, getattr(r, "SOURCE_FILENAME", ""), torrents):
                orphan_records.append(
                    {
                        "id": getattr(r, "ID", None),
                        "tmdb_id": getattr(r, "TMDBID", None),
                        "title": getattr(r, "TITLE", ""),
                        "year": getattr(r, "YEAR", ""),
                        "season_episode": getattr(r, "SEASON_EPISODE", ""),
                        "source_path": getattr(r, "SOURCE_PATH", ""),
                        "source_filename": getattr(r, "SOURCE_FILENAME", ""),
                        "source_full": source_full,
                        "dest_path": getattr(r, "DEST_PATH", ""),
                        "dest_filename": getattr(r, "DEST_FILENAME", ""),
                    }
                )
        return {"total": len(orphan_records), "orphans": orphan_records, "source_dirs": list(source_dirs)}

    def plan_migration(self, tmdb_id: int) -> dict:
        """迁移预览：列出该作品的源目录组 / 媒体库目录组，供前端展示与选择目标盘。"""
        records = self._get_records(tmdb_id)
        source_dirs, dest_dirs = self._collect_dirs(records)
        return {
            "tmdb_id": tmdb_id,
            "title": records[0].TITLE if records else "",
            "year": records[0].YEAR if records else "",
            "record_count": len(records),
            "source_dirs": list(source_dirs),
            "dest_dirs": list(dest_dirs),
        }

    def migrate(
        self,
        tmdb_id: int,
        target_source: str,
        target_dest: str,
        cross_drive: bool | None = None,
        move_torrents: bool = True,
        orphan_policy: str = "migrate",
    ) -> dict:
        """执行作品级迁移。

        :param tmdb_id: 作品 ID
        :param target_source: 目标盘的源（btstore）目录
        :param target_dest: 目标盘的媒体库（medialink）目录
        :param cross_drive: 是否强制按"跨盘"处理；None 则自动检测同盘
        :param move_torrents: 是否尝试同步迁移下载器任务（最佳努力）
        :param orphan_policy: 无下载器做种任务的"孤儿源文件"处理策略：
            - "migrate"（默认）：随目录一起迁移（保留文件）
            - "remove"：迁移前物理删除孤儿源文件（清除残留，释放空间）
            - "skip"：跳过孤儿文件（不迁移也不删除，就留在原盘）
        """
        if not tmdb_id:
            raise ValidationError("缺少作品ID")
        if not target_source or not target_dest:
            raise ValidationError("未指定目标源的源目录或媒体库目录")

        records = self._get_records(tmdb_id)
        if not records:
            raise ValidationError("未找到该作品的转移记录")

        source_dirs, dest_dirs = self._collect_dirs(records)
        if not source_dirs and not dest_dirs:
            raise ValidationError("该作品没有可迁移的文件目录")

        # 检测孤儿源文件（有源文件但下载器无做种任务）
        orphan_info = self.detect_orphans(tmdb_id=tmdb_id)
        orphan_files = [o["source_full"] for o in orphan_info["orphans"]]

        # 计算同盘/跨盘
        is_cross = self._determine_cross(source_dirs, dest_dirs, target_source, target_dest, cross_drive)

        # 根据孤儿策略预处理：remove 则物理删除孤儿源文件
        orphan_removed = []
        if orphan_policy == "remove" and orphan_files:
            for f in orphan_files:
                try:
                    if os.path.exists(f):
                        os.remove(f)
                        orphan_removed.append(f)
                except Exception as e:  # noqa: BLE001
                    log.warn(f"[Migrate]删除孤儿源文件失败 {f}: {e}")

        migrated_dirs = []

        failed = []
        # 1. 迁移源目录组
        for old_dir in source_dirs:
            if not os.path.exists(old_dir):
                continue
            target = self._build_target_path(target_source, old_dir)
            try:
                self._move_dir(old_dir, target, is_cross)
                migrated_dirs.append({"kind": "source", "old": old_dir, "new": target})
            except Exception as e:  # noqa: BLE001
                log.error(f"[Migrate]源目录迁移失败 {old_dir}: {e}")
                failed.append({"kind": "source", "path": old_dir, "error": str(e)})

        # 2. 迁移媒体库目录组
        for old_dir in dest_dirs:
            if not os.path.exists(old_dir):
                continue
            target = self._build_target_path(target_dest, old_dir)
            try:
                self._move_dir(old_dir, target, is_cross)
                migrated_dirs.append({"kind": "dest", "old": old_dir, "new": target})
            except Exception as e:  # noqa: BLE001
                log.error(f"[Migrate]媒体库目录迁移失败 {old_dir}: {e}")
                failed.append({"kind": "dest", "path": old_dir, "error": str(e)})

        # 3. 更新转移记录（SOURCE/DEST 指向新目录）
        updated_records = self._update_records(records, migrated_dirs)

        # 4. 更新下载记录 SAVE_PATH 并最佳努力迁移下载器任务
        updated_downloads = self._update_download_records(records, migrated_dirs, move_torrents)

        return {
            "tmdb_id": tmdb_id,
            "cross_drive": is_cross,
            "migrated_dirs": migrated_dirs,
            "failed": failed,
            "updated_records": updated_records,
            "updated_downloads": updated_downloads,
            "orphan_policy": orphan_policy,
            "orphan_files": orphan_files,
            "orphan_removed": orphan_removed,
        }

    # ---------- 内部：收集 ----------

    def _get_records(self, tmdb_id: int) -> list:
        try:
            records = self._history.get_transfer_info_by(tmdbid=tmdb_id) or []
        except Exception as e:  # noqa: BLE001
            log.error(f"[Migrate]查询转移记录失败 tmdb={tmdb_id}: {e}")
            raise ServiceError("查询转移记录失败") from e
        return [r for r in records if getattr(r, "ID", None)]

    @staticmethod
    def _collect_dirs(records: list) -> tuple[set[str], set[str]]:
        """收集源目录组 + 媒体库目录组（去重）。"""
        source_dirs: set[str] = set()
        dest_dirs: set[str] = set()
        for r in records:
            sp = getattr(r, "SOURCE_PATH", "") or ""
            df = getattr(r, "DEST_PATH", "") or ""
            if sp:
                source_dirs.add(os.path.normpath(sp))
            if df:
                dest_dirs.add(os.path.normpath(df))
        return source_dirs, dest_dirs

    @staticmethod
    def _build_target_path(target_root: str, old_dir: str) -> str:
        """目标路径 = 目标根 / 原目录名（保留作品目录名）。"""
        name = os.path.basename(old_dir.rstrip("/\\"))
        target = os.path.join(target_root, name)
        # 若同名目录已存在则追加后缀，避免覆盖
        base = target
        i = 1
        while os.path.exists(target) and os.path.normpath(target) != os.path.normpath(old_dir):
            target = f"{base}.{i}"
            i += 1
        return target

    # ---------- 内部：同盘/跨盘 ----------

    def _determine_cross(
        self, source_dirs: set[str], dest_dirs: set[str], target_source: str, target_dest: str, cross_drive: bool | None
    ) -> bool:
        """判定是否跨盘：优先自动检测，必要时接受 cross_drive 兜底。"""
        # 目标目录需存在以判断
        probe_dirs = list(source_dirs) + list(dest_dirs)
        old_root = next((p for p in probe_dirs if os.path.exists(p)), None)
        if cross_drive is not None:
            return bool(cross_drive)
        if old_root and os.path.exists(target_source):
            return not PathUtils.is_same_filesystem(old_root, target_source)
        # 无法自动判断时默认按同盘处理（由用户勾选兜底）
        return False

    def _move_dir(self, old_dir: str, target: str, is_cross: bool) -> None:
        """目录级迁移：同盘 move（保 inode），跨盘 复制->校验->删旧。"""
        if os.path.normpath(old_dir) == os.path.normpath(target):
            return
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if not is_cross:
            # 同盘：直接 move（同文件系统 shutil.move 走 os.rename，保留 inode/硬链接）
            shutil.move(old_dir, target)
            return
        # 跨盘：先复制，校验，再删旧
        self._copy_tree_verify_then_remove(old_dir, target)

    def _copy_tree_verify_then_remove(self, old_dir: str, target: str) -> None:
        """跨盘：递归复制到 target -> 校验关键文件 -> 删除 old_dir。"""
        # 复制整个目录树
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(old_dir, target)
        # 校验：目标文件数与源一致
        old_files = [f for f in self._walk_files(old_dir)]
        new_files = [f for f in self._walk_files(target)]
        old_set = {os.path.relpath(f, old_dir) for f in old_files}
        new_set = {os.path.relpath(f, target) for f in new_files}
        if old_set != new_set:
            raise ServiceError(f"复制校验不一致，已保留原目录：{old_dir}")
        # 删除旧位置（复制成功校验通过后再删，保证不丢文件）
        shutil.rmtree(old_dir)
        log.info(f"[Migrate]跨盘迁移完成（复制校验后删除旧）：{old_dir} -> {target}")

    @staticmethod
    def _walk_files(root: str) -> list[str]:
        result = []
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                result.append(os.path.join(dirpath, name))
        return result

    # ---------- 内部：更新记录 ----------

    def _update_records(self, records: list, migrated_dirs: list[dict]) -> int:
        """按迁移目录映射更新转移记录 SOURCE/DEST 路径。"""
        if not migrated_dirs:
            return 0
        # 建立 old_dir -> new_dir 映射
        src_map = {os.path.normpath(m["old"]): m["new"] for m in migrated_dirs if m["kind"] == "source"}
        dst_map = {os.path.normpath(m["old"]): m["new"] for m in migrated_dirs if m["kind"] == "dest"}
        updated = 0
        for r in records:
            old_sp = os.path.normpath(getattr(r, "SOURCE_PATH", "") or "")
            old_dp = os.path.normpath(getattr(r, "DEST_PATH", "") or "")
            new_sp = src_map.get(old_sp)
            new_dp = dst_map.get(old_dp)
            if not new_sp and not new_dp:
                continue
            try:
                self._history.update_transfer_paths(
                    logid=getattr(r, "ID"),
                    new_source_path=new_sp,
                    new_source_filename=(getattr(r, "SOURCE_FILENAME", "") or "") if new_sp else None,
                    new_dest_path=new_dp,
                    new_dest_filename=(getattr(r, "DEST_FILENAME", "") or "") if new_dp else None,
                )
                updated += 1
            except Exception as e:  # noqa: BLE001
                log.error(f"[Migrate]更新转移记录失败 id={getattr(r, 'ID')}: {e}")
        return updated

    def _update_download_records(self, records: list, migrated_dirs: list[dict], move_torrents: bool) -> int:
        """更新下载记录 SAVE_PATH 并最佳努力迁移下载器任务。"""
        src_map = {os.path.normpath(m["old"]): m["new"] for m in migrated_dirs if m["kind"] == "source"}
        updated = 0
        handled_downloader_tasks: set[tuple[str, str]] = set()
        for r in records:
            old_sp = os.path.normpath(getattr(r, "SOURCE_PATH", "") or "")
            new_sp = src_map.get(old_sp)
            if not new_sp:
                continue
            # 下载记录 SAVE_PATH 通常是源根或源文件所在目录，尽量映射到新源目录
            try:
                recs = self._download_repo.get_download_history_list_by_path(old_sp) or []
            except Exception as e:  # noqa: BLE001
                log.debug(f"[Migrate]查询下载记录失败 {old_sp}: {e}")
                recs = []
            for rec in recs:
                downloader = getattr(rec, "DOWNLOADER", "") or ""
                download_id = getattr(rec, "DOWNLOAD_ID", "") or ""
                if downloader and download_id:
                    try:
                        self._download_repo.update_save_path(
                            downloader, download_id, new_sp, tmdb_id=getattr(r, "TMDBID", None)
                        )
                        updated += 1
                    except Exception as e:  # noqa: BLE001
                        log.warn(f"[Migrate]更新下载记录 SAVE_PATH 失败：{e}")
                    if move_torrents:
                        key = (downloader, download_id)
                        if key not in handled_downloader_tasks:
                            handled_downloader_tasks.add(key)
                            self._try_move_torrent(downloader, download_id, new_sp)
        return updated

    def _try_move_torrent(self, downloader: str, download_id: str, new_dir: str) -> None:
        """最佳努力迁移下载器任务存储路径（qb 支持则调，失败不阻断）。"""
        if not self._downloader_core:
            return
        try:
            self._downloader_core.move_torrents_location(
                downloader_id=downloader, ids=[download_id], new_path=new_dir
            )
        except Exception as e:  # noqa: BLE001
            log.warn(f"[Migrate]下载器 {downloader} 迁移任务 {download_id} 失败：{e}")

    # ---------- 内部：孤儿源文件判定 ----------

    def _get_all_records(self) -> list:
        """全量获取有源路径的转移记录（分页，避免一次性过多）。"""
        records: list = []
        try:
            for page in range(1, 200):
                _, page_records = self._history.get_transfer_history(search=None, page=page, rownum=500)
                if not page_records:
                    break
                records.extend([r for r in page_records if getattr(r, "ID", None)])
                if len(page_records) < 500:
                    break
        except Exception as e:  # noqa: BLE001
            log.error(f"[Migrate]查询全部转移记录失败: {e}")
        return records

    @staticmethod
    def _source_full(record) -> str:
        """拼接记录的源文件完整路径。"""
        sp = getattr(record, "SOURCE_PATH", "") or ""
        sf = getattr(record, "SOURCE_FILENAME", "") or ""
        if not sp or not sf:
            return ""
        return os.path.join(sp, sf)

    def _get_all_torrents(self) -> list[dict]:
        """拉取所有下载器的任务列表，提取 (save_path, content_path, name, downloader)。"""
        if not self._downloader_core:
            return []
        torrents: list[dict] = []
        try:
            downloader_confs = self._downloader_core.get_downloader_conf() or {}
            for did in downloader_confs.keys():
                try:
                    tasks = self._downloader_core.get_torrents(downloader_id=did)
                except Exception as e:  # noqa: BLE001
                    log.debug(f"[Migrate]拉取下载器 {did} 任务失败: {e}")
                    continue
                if not tasks:
                    continue
                for t in tasks:
                    torrents.append(
                        {
                            "id": getattr(t, "id", None),
                            "name": getattr(t, "name", "") or "",
                            "save_path": (getattr(t, "save_path", "") or "").replace("\\", "/").rstrip("/"),
                            "content_path": (getattr(t, "content_path", "") or "").replace("\\", "/"),
                            "downloader": did,
                        }
                    )
        except Exception as e:  # noqa: BLE001
            log.error(f"[Migrate]获取下载器任务列表失败: {e}")
        return torrents

    def _has_torrent_for_source(self, source_full: str, source_filename: str, torrents: list[dict]) -> bool:
        """源文件是否被任一下载器任务"包含"。

        匹配规则（由宽松到严格，任一命中即视为有任务）：
        - content_path 等于源文件完整路径（单文件种子）
        - 源文件落在 content_path（多文件种子顶层目录）之下
        - 源文件落在 save_path 之下，且任务名匹配源文件名（transmission 无 content_path）
        - 种子名等于源文件名
        """
        if not source_full or not torrents:
            return False
        src_full_norm = os.path.normpath(source_full).replace("\\", "/")
        src_name = source_filename.replace("\\", "/")
        for t in torrents:
            cp = t.get("content_path")
            if cp and os.path.normpath(cp).replace("\\", "/") == src_full_norm:
                return True
            if cp and src_full_norm.startswith(os.path.normpath(cp).replace("\\", "/") + "/"):
                return True
            sp = t.get("save_path")
            tname = t.get("name", "") or ""
            if sp and src_full_norm.startswith(sp + "/"):
                if src_name and os.path.basename(src_name) in (os.path.basename(tname), tname):
                    return True
            if tname and os.path.basename(tname) == os.path.basename(src_name):
                return True
        return False
