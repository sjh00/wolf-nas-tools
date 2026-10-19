"""批量重命名执行与回滚测试."""

from __future__ import annotations

import json
import os

import pytest

from app.services.transfer import library_rename_executor as executor_module
from app.services.transfer.library_rename_executor import LibraryRenameExecutor


class _FakeLock:
    def acquire(self) -> bool:
        return True

    def release(self) -> None:
        return None


class _FakeLockManager:
    def create_lock(self, *_args, **_kwargs):
        return _FakeLock()


class _FakeStorageRepo:
    def get_by_id(self, _sid):
        return None


class _FakeRepo:
    def __init__(self, items):
        self.items = {int(item["ID"]): dict(item) for item in items}
        self.history_updates = []
        self.metadata_upserts = []
        self.metadata_path_updates = []
        self.job_status = {}

    def get_job(self, _job_id):
        return {"ID": 1, "STATUS": self.job_status.get("STATUS", "running")}

    def update_job_status(self, _job_id, status, **kwargs):
        self.job_status["STATUS"] = status
        self.job_status.update(kwargs)

    def list_all_items(self, _job_id):
        return list(self.items.values())

    def list_planned_items(self, _job_id):
        return [item for item in self.items.values() if item.get("STATUS") == "planned"]

    def update_item(self, item_id, **kwargs):
        self.items[int(item_id)].update(kwargs)

    def update_history_dest(self, old_dir, old_file, new_dir, new_file, category=None):
        self.history_updates.append((old_dir, old_file, new_dir, new_file, category))
        return 1

    def upsert_metadata(self, backend_id, path, data, **_kwargs):
        self.metadata_upserts.append((backend_id, path, data))

    def update_metadata_path(self, backend_id, old_path, new_path, **_kwargs):
        self.metadata_path_updates.append((backend_id, old_path, new_path))


@pytest.fixture
def rename_executor(monkeypatch, tmp_path):
    root = tmp_path / "library"
    old_dir = root / "Old Movie (2020)"
    old_dir.mkdir(parents=True)
    old_video = old_dir / "Old Movie (2020).mkv"
    old_video.write_bytes(b"video")
    (old_dir / "Old Movie (2020).zh.srt").write_text("sub", encoding="utf-8")
    (old_dir / "Old Movie (2020).nfo").write_text("<movie/>", encoding="utf-8")
    (old_dir / "poster.jpg").write_bytes(b"poster")
    new_dir = root / "New Movie (2020)"
    new_video = new_dir / "New Movie (2020).mkv"

    item = {
        "ID": 1,
        "JOB_ID": 1,
        "BACKEND_ID": "local",
        "ROOT": str(root),
        "OLD_PATH": str(old_video),
        "NEW_PATH": str(new_video),
        "OLD_PATH_HASH": "hash",
        "OLD_SIZE": os.path.getsize(old_video),
        "OLD_MTIME": os.path.getmtime(old_video),
        "METADATA_SOURCE": "history",
        "METADATA_SNAPSHOT": json.dumps(
            {
                "type": "movie",
                "title": "New Movie",
                "year": "2020",
                "tmdbid": "100",
                "season": None,
                "source": "history",
                "confidence": "high",
            }
        ),
        "ACTION": "rename",
        "STATUS": "planned",
        "AUX_MOVES": None,
    }
    repo = _FakeRepo([item])
    monkeypatch.setattr(executor_module, "get_lock_manager", lambda: _FakeLockManager())
    executor = LibraryRenameExecutor(repo, _FakeStorageRepo())
    return executor, repo, root, old_video, new_video, old_dir, new_dir


def test_execute_moves_video_and_aux_then_shared_assets(rename_executor):
    executor, repo, root, old_video, new_video, old_dir, new_dir = rename_executor
    item = repo.items[1]
    executor._execute_item(item)

    assert not old_video.exists()
    assert new_video.exists()
    assert (new_dir / "New Movie (2020).zh.srt").exists()
    assert (new_dir / "New Movie (2020).nfo").exists()
    assert repo.items[1]["STATUS"] == "done"
    assert repo.history_updates
    assert repo.metadata_upserts

    groups = executor._directory_groups(repo.list_all_items(1))
    executor._finish_directory_assets(groups)
    assert (new_dir / "poster.jpg").exists()
    assert not old_dir.exists()
    assert repo.items[1]["AUX_MOVES"]


def test_rollback_restores_video_aux_and_shared_assets(rename_executor):
    executor, repo, root, old_video, new_video, old_dir, new_dir = rename_executor
    item = repo.items[1]
    executor._execute_item(item)
    groups = executor._directory_groups(repo.list_all_items(1))
    executor._finish_directory_assets(groups)

    assert executor._rollback_item(repo.items[1])
    assert old_video.exists()
    assert (old_dir / "Old Movie (2020).zh.srt").exists()
    assert (old_dir / "Old Movie (2020).nfo").exists()
    assert (old_dir / "poster.jpg").exists()
    assert repo.items[1]["STATUS"] == "rolled_back"
    assert repo.metadata_path_updates


def test_target_exists_is_failed_without_moving(rename_executor):
    executor, repo, root, old_video, new_video, old_dir, new_dir = rename_executor
    new_dir.mkdir(parents=True)
    new_video.write_bytes(b"other")
    executor._execute_item(repo.items[1])

    assert old_video.exists()
    assert new_video.read_bytes() == b"other"
    assert repo.items[1]["STATUS"] == "failed"
    assert repo.items[1]["ERROR"] == "target_exists"
