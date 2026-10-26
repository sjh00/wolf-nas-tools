"""批量重命名执行、回滚与目录级资产处理."""

from __future__ import annotations

import os
from typing import Any

import log
from app.core.constants import RMT_AUDIO_TRACK_EXT, RMT_MEDIAEXT, RMT_SUBEXT
from app.db.repositories.library_rename_repository import now_str
from app.infrastructure.distributed_lock.lock_manager import get_lock_manager
from app.services.transfer.library_rename_backend import (
    basename,
    dirname,
    norm_path,
    normalize_backend,
    resolve_backend,
    target_dir_lock_key,
)
from app.storage.backends.base import StorageBackend
from app.utils import PathUtils
from app.utils.json_utils import JsonUtils

_SUBTITLE_EXTS = set(RMT_SUBEXT) | {".vtt", ".sup", ".sub", ".idx"}
_AUDIO_EXTS = set(RMT_AUDIO_TRACK_EXT)
_MEDIA_EXTS = set(RMT_MEDIAEXT)
_SHARED_NFO = {"movie.nfo", "tvshow.nfo", "season.nfo"}


class LibraryRenameExecutor:
    """执行已确认的 rename plan."""

    def __init__(self, rename_repo, storage_repo, media_server=None, on_finished=None):
        self._repo = rename_repo
        self._storage_repo = storage_repo
        self._media_server = media_server
        self._on_finished = on_finished

    # ---------- job ----------

    def run_job(self, job_id: int) -> None:
        job = self._repo.get_job(job_id)
        if not job or job.get("STATUS") != "planned":
            return
        lock = get_lock_manager().create_lock(f"library:rename:job:{job_id}", ttl_seconds=1800)
        if not lock.acquire():
            log.warn(f"[LibraryRename]任务 {job_id} 已在执行")
            return
        try:
            self._repo.update_job_status(job_id, "running", STARTED_AT=now_str())
            lock_lost = False
            for item in self._repo.list_planned_items(job_id):
                job = self._repo.get_job(job_id) or {}
                if job.get("STATUS") in ("cancelling", "cancelled"):
                    break
                self._execute_item(item)
                if not lock.extend(1800):
                    log.error(f"[LibraryRename]任务 {job_id} 锁已丢失，停止执行")
                    lock_lost = True
                    break
            if not lock_lost:
                try:
                    self._finish_directory_assets(self._directory_groups(self._repo.list_all_items(job_id)))
                except Exception as e:  # noqa: BLE001
                    log.error(f"[LibraryRename]处理目录级资产失败: {e}")
            self._refresh_media_server(job_id)
            job = self._repo.get_job(job_id) or {}
            if lock_lost:
                final_status = "interrupted"
            elif job.get("STATUS") in ("cancelling", "cancelled"):
                final_status = "cancelled"
            else:
                final_status = "completed"
            self._repo.refresh_job_counters(job_id)
            self._repo.update_job_status(job_id, final_status, FINISHED_AT=now_str())
        except Exception as e:  # noqa: BLE001
            log.error(f"[LibraryRename]任务 {job_id} 执行失败: {e}")
            self._repo.refresh_job_counters(job_id)
            self._repo.update_job_status(job_id, "failed", FINISHED_AT=now_str())
        finally:
            lock.release()
            self._notify_finished()

    def cancel_job(self, job_id: int) -> bool:
        job = self._repo.get_job(job_id)
        if not job:
            return False
        if job.get("STATUS") == "planned":
            self._repo.update_job_status(job_id, "cancelled", FINISHED_AT=now_str())
            return True
        if job.get("STATUS") == "running":
            self._repo.update_job_status(job_id, "cancelling")
            return True
        return False

    def rollback_job(self, job_id: int) -> dict[str, Any]:
        job = self._repo.get_job(job_id)
        if not job:
            return {"ok": False, "reason": "job_not_found"}
        if job.get("STATUS") == "running":
            return {"ok": False, "reason": "job_running"}
        lock = get_lock_manager().create_lock(f"library:rename:job:{job_id}", ttl_seconds=3600)
        if not lock.acquire():
            return {"ok": False, "reason": "job_locked"}
        rolled_back = 0
        failed = 0
        try:
            for item in self._repo.list_done_items(job_id):
                if item.get("STATUS") != "done":
                    continue
                if self._rollback_item(item):
                    rolled_back += 1
                else:
                    failed += 1
            self._repo.update_job_status(job_id, "rolled_back", FINISHED_AT=now_str())
            self._repo.refresh_job_counters(job_id)
            self._refresh_media_server(job_id)
            return {"ok": True, "rolled_back": rolled_back, "failed": failed}
        finally:
            lock.release()
            self._notify_finished()

    # ---------- item ----------

    def _execute_item(self, item: dict[str, Any]) -> None:
        item_id = int(item["ID"])
        old_path = norm_path(item["OLD_PATH"])
        new_path = norm_path(item.get("NEW_PATH") or "")
        backend = resolve_backend(self._storage_repo, item.get("BACKEND_ID"))
        if backend is None:
            self._fail(item_id, "backend_unavailable")
            return
        if not new_path:
            self._fail(item_id, "missing_new_path")
            return
        root = norm_path(item.get("ROOT") or "")
        if not root or not PathUtils.is_path_in_path(root, old_path) or not PathUtils.is_path_in_path(root, new_path):
            self._fail(item_id, "outside_library_root")
            return
        stat = backend.stat(old_path)
        if stat is None:
            self._fail(item_id, "source_missing")
            return
        if item.get("OLD_SIZE") is not None and int(item["OLD_SIZE"]) != int(stat.size):
            self._fail(item_id, "file_changed")
            return
        if item.get("OLD_MTIME") is not None and abs(float(item["OLD_MTIME"]) - float(stat.mtime)) > 2:
            self._fail(item_id, "file_changed")
            return
        if backend.exists(new_path):
            self._fail(item_id, "target_exists")
            return

        lock_keys = sorted(
            {
                target_dir_lock_key(item.get("BACKEND_ID"), dirname(old_path)),
                target_dir_lock_key(item.get("BACKEND_ID"), dirname(new_path)),
            }
        )
        locks = []
        for lock_key in lock_keys:
            lock = get_lock_manager().create_lock(lock_key, ttl_seconds=1800)
            if not lock.acquire():
                for acquired in reversed(locks):
                    acquired.release()
                self._fail(item_id, "target_locked")
                return
            locks.append(lock)

        moved_video = False
        aux_moves: list[list[str]] = []
        try:
            if backend.exists(new_path):
                self._fail(item_id, "target_exists")
                return
            self._repo.update_item(item_id, STATUS="running")
            backend.mkdir(dirname(new_path), parents=True)
            backend.move(old_path, new_path)
            moved_video = True
            aux_moves = self._move_aux(backend, old_path, new_path)
            self._repo.update_history_dest(
                dirname(old_path),
                basename(old_path),
                dirname(new_path),
                basename(new_path),
                category=self._history_category(item, target=True),
            )
            new_stat = backend.stat(new_path)
            self._repo.update_metadata_path(
                normalize_backend(item.get("BACKEND_ID")),
                old_path,
                new_path,
                file_size=new_stat.size if new_stat else None,
                file_mtime=new_stat.mtime if new_stat else None,
            )
            self._upsert_metadata(item, backend, new_path)
            self._repo.update_item(
                item_id,
                STATUS="done",
                NEW_PATH=new_path,
                AUX_MOVES=JsonUtils.dumps(aux_moves, ensure_ascii=False),
            )
        except Exception as e:  # noqa: BLE001
            log.error(f"[LibraryRename]改名失败 {old_path} -> {new_path}: {e}")
            try:
                self._repo.update_history_dest(
                    dirname(new_path),
                    basename(new_path),
                    dirname(old_path),
                    basename(old_path),
                    category=self._history_category(item, target=False),
                )
            except Exception as rollback_error:  # noqa: BLE001
                log.warn(f"[LibraryRename]回滚历史失败: {rollback_error}")
            try:
                self._repo.update_metadata_path(normalize_backend(item.get("BACKEND_ID")), new_path, old_path)
            except Exception as rollback_error:  # noqa: BLE001
                log.warn(f"[LibraryRename]回滚元数据缓存失败: {rollback_error}")
            rollback_ok = self._rollback_paths(backend, old_path, new_path, aux_moves if moved_video else [])
            self._repo.update_item(
                item_id,
                STATUS="manual_intervention" if not rollback_ok else "failed",
                ERROR=str(e),
                ROLLBACK_STATUS="done" if rollback_ok else "failed",
            )
        finally:
            for acquired in reversed(locks):
                acquired.release()

    def _move_aux(self, backend: StorageBackend, old_path: str, new_path: str) -> list[list[str]]:
        old_dir = dirname(old_path)
        new_dir = dirname(new_path)
        old_base = os.path.splitext(basename(old_path))[0]
        new_base = os.path.splitext(basename(new_path))[0]
        moved: list[list[str]] = []
        try:
            entries = list(backend.list_dir(old_dir))
        except Exception as e:  # noqa: BLE001
            log.warn(f"[LibraryRename]列取附属文件失败 {old_dir}: {e}")
            return moved
        for entry in entries:
            if entry.is_dir:
                continue
            name = basename(entry.path)
            stem, ext = os.path.splitext(name)
            ext = ext.lower()
            target_name: str | None = None
            if ext in _SUBTITLE_EXTS and (stem == old_base or stem.startswith(old_base + ".")):
                target_name = new_base + stem[len(old_base) :] + ext
            elif ext in _AUDIO_EXTS and stem == old_base:
                target_name = new_base + ext
            elif ext == ".nfo" and stem == old_base and name.lower() not in _SHARED_NFO:
                target_name = new_base + ".nfo"
            if not target_name:
                continue
            target = os.path.join(new_dir, target_name)
            if backend.exists(target):
                continue
            try:
                backend.mkdir(new_dir, parents=True)
                backend.move(entry.path, target)
                moved.append([norm_path(entry.path), norm_path(target)])
            except Exception as e:  # noqa: BLE001
                log.warn(f"[LibraryRename]移动附属文件失败 {entry.path}: {e}")
        return moved

    def _upsert_metadata(self, item: dict[str, Any], backend: StorageBackend, new_path: str) -> None:
        try:
            snapshot = JsonUtils.loads(item.get("METADATA_SNAPSHOT") or "{}")
        except Exception:  # noqa: BLE001
            snapshot = {}
        stat = backend.stat(new_path)
        data = {
            "type": snapshot.get("type") or "",
            "title": snapshot.get("title") or "",
            "year": snapshot.get("year") or "",
            "tmdbid": snapshot.get("tmdbid") or "",
            "anchor_provider": snapshot.get("anchor_provider"),
            "anchor_external_id": snapshot.get("anchor_external_id"),
            "identity_id": snapshot.get("identity_id"),
            "content_profile": snapshot.get("content_profile") or "default",
            "season": snapshot.get("season") or "",
            "episode": snapshot.get("episode") or "",
            "season_episode_count": snapshot.get("season_episode_count"),
            "source_filename": snapshot.get("source_filename"),
            "metadata_source": snapshot.get("source") or item.get("METADATA_SOURCE") or "",
            "confidence": snapshot.get("confidence") or "medium",
            "is_manual": bool(snapshot.get("is_manual")),
            "file_size": stat.size if stat else None,
            "file_mtime": stat.mtime if stat else None,
            "raw": snapshot,
        }
        self._repo.upsert_metadata(normalize_backend(item.get("BACKEND_ID")), new_path, data, is_manual=False)

    @staticmethod
    def _history_category(item: dict[str, Any], *, target: bool) -> str | None:
        try:
            snapshot = JsonUtils.loads(item.get("METADATA_SNAPSHOT") or "{}")
        except Exception:  # noqa: BLE001
            return None
        if not snapshot.get("update_category"):
            return None
        key = "target_category" if target else "category"
        return str(snapshot.get(key) or "")

    def _notify_finished(self) -> None:
        if self._on_finished is None:
            return
        try:
            self._on_finished()
        except Exception as e:  # noqa: BLE001
            log.warn(f"[LibraryRename]刷新历史缓存失败: {e}")

    def _refresh_media_server(self, job_id: int) -> None:
        if self._media_server is None:
            return
        items = []
        seen: set[tuple[str, str]] = set()
        for item in self._repo.list_all_items(job_id):
            if item.get("STATUS") not in ("done", "rolled_back"):
                continue
            try:
                snapshot = JsonUtils.loads(item.get("METADATA_SNAPSHOT") or "{}")
            except Exception:  # noqa: BLE001
                snapshot = {}
            for path in (item.get("OLD_PATH"), item.get("NEW_PATH")):
                if not path:
                    continue
                key = (str(item.get("BACKEND_ID")), norm_path(path))
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    {
                        "file_path": path,
                        "title": snapshot.get("title") or "",
                        "year": snapshot.get("year") or "",
                        "type": snapshot.get("type") or "",
                        "content_profile": snapshot.get("content_profile") or "default",
                        "target_path": path,
                    }
                )
        if not items:
            return
        try:
            grouped: dict[str, list[dict]] = {}
            for item in items:
                grouped.setdefault(item.get("content_profile") or "default", []).append(item)
            for profile, profile_items in grouped.items():
                self._media_server.refresh_library_by_items(profile_items, content_profile=profile)
        except Exception as e:  # noqa: BLE001
            log.warn(f"[LibraryRename]刷新媒体服务器失败: {e}")

    def _fail(self, item_id: int, reason: str) -> None:
        self._repo.update_item(item_id, STATUS="failed", ERROR=reason)

    # ---------- rollback ----------

    def _rollback_item(self, item: dict[str, Any]) -> bool:
        old_path = norm_path(item["OLD_PATH"])
        new_path = norm_path(item.get("NEW_PATH") or "")
        if not new_path:
            return True
        backend = resolve_backend(self._storage_repo, item.get("BACKEND_ID"))
        if backend is None:
            self._repo.update_item(int(item["ID"]), ROLLBACK_STATUS="failed", STATUS="manual_intervention")
            return False
        try:
            aux = JsonUtils.loads(item.get("AUX_MOVES") or "[]")
        except Exception:  # noqa: BLE001
            aux = []
        ok = self._rollback_paths(backend, old_path, new_path, aux)
        if ok:
            self._repo.update_history_dest(
                dirname(new_path),
                basename(new_path),
                dirname(old_path),
                basename(old_path),
                category=self._history_category(item, target=False),
            )
            self._repo.update_metadata_path(normalize_backend(item.get("BACKEND_ID")), new_path, old_path)
            self._repo.update_item(int(item["ID"]), STATUS="rolled_back", ROLLBACK_STATUS="done")
        else:
            self._repo.update_item(int(item["ID"]), STATUS="manual_intervention", ROLLBACK_STATUS="failed")
        return ok

    def _rollback_paths(
        self,
        backend: StorageBackend,
        old_path: str,
        new_path: str,
        aux_moves: list[list[str]],
    ) -> bool:
        ok = True
        for old_aux, new_aux in reversed(aux_moves):
            new_exists = backend.exists(new_aux)
            old_exists = backend.exists(old_aux)
            if new_exists and old_exists:
                log.warn(f"[LibraryRename]回滚冲突，源与目标同时存在 {old_aux} / {new_aux}")
                ok = False
            elif new_exists:
                try:
                    backend.mkdir(dirname(old_aux), parents=True)
                    backend.move(new_aux, old_aux)
                except Exception as e:  # noqa: BLE001
                    log.error(f"[LibraryRename]回滚附属文件失败 {new_aux}: {e}")
                    ok = False
        new_exists = backend.exists(new_path)
        old_exists = backend.exists(old_path)
        if new_exists and old_exists:
            log.warn(f"[LibraryRename]回滚冲突，源与目标同时存在 {old_path} / {new_path}")
            ok = False
        elif new_exists:
            try:
                backend.mkdir(dirname(old_path), parents=True)
                backend.move(new_path, old_path)
            except Exception as e:  # noqa: BLE001
                log.error(f"[LibraryRename]回滚主文件失败 {new_path}: {e}")
                ok = False
        elif not old_exists:
            log.error(f"[LibraryRename]回滚失败，源与目标都不存在 {old_path} / {new_path}")
            ok = False
        return ok

    # ---------- shared assets ----------

    def _directory_groups(self, items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for item in items:
            if item.get("ACTION") != "rename" or not item.get("NEW_PATH"):
                continue
            old_dir = dirname(item["OLD_PATH"])
            group = groups.setdefault(
                old_dir,
                {"new_dirs": set(), "items": [], "invalid": False, "first_item": item},
            )
            group["new_dirs"].add(dirname(item["NEW_PATH"]))
            group["items"].append(item)
        return groups

    def _finish_directory_assets(self, groups: dict[str, dict[str, Any]]) -> None:
        for old_dir, group in groups.items():
            new_dirs = group["new_dirs"]
            if len(new_dirs) != 1:
                continue
            new_dir = next(iter(new_dirs))
            if norm_path(old_dir) == norm_path(new_dir):
                continue
            items = group["items"]
            if any(item.get("STATUS") != "done" for item in items):
                continue
            backend = resolve_backend(self._storage_repo, items[0].get("BACKEND_ID"))
            if backend is None:
                continue
            try:
                entries = list(backend.list_dir(old_dir))
            except Exception:  # noqa: BLE001
                continue
            if any(
                not entry.is_dir and os.path.splitext(basename(entry.path))[1].lower() in _MEDIA_EXTS
                for entry in entries
            ):
                continue
            moved: list[list[str]] = []
            for entry in entries:
                if entry.is_dir:
                    continue
                target = os.path.join(new_dir, basename(entry.path))
                if backend.exists(target):
                    continue
                try:
                    backend.mkdir(new_dir, parents=True)
                    backend.move(entry.path, target)
                    moved.append([norm_path(entry.path), norm_path(target)])
                except Exception as e:  # noqa: BLE001
                    log.warn(f"[LibraryRename]移动目录级资产失败 {entry.path}: {e}")
            if moved:
                first = group["first_item"]
                try:
                    existing = JsonUtils.loads(first.get("AUX_MOVES") or "[]")
                except Exception:  # noqa: BLE001
                    existing = []
                existing.extend(moved)
                first["AUX_MOVES"] = JsonUtils.dumps(existing, ensure_ascii=False)
                self._repo.update_item(int(first["ID"]), AUX_MOVES=first["AUX_MOVES"])
            try:
                if not list(backend.list_dir(old_dir)):
                    backend.remove(old_dir)
            except Exception as e:  # noqa: BLE001
                log.debug(f"[LibraryRename]删除空目录失败 {old_dir}: {e}")
