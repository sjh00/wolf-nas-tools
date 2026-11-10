"""按识别记录定位下载器任务（「同时移除种子」的匹配逻辑）."""

import os

from app.services.transfer.torrent_locator import candidate_dirs, locate_download_tasks


class _Record:
    def __init__(self, downloader, download_id):
        self.DOWNLOADER = downloader
        self.DOWNLOAD_ID = download_id


def _repo(mapping):
    """mapping: {目录: [(downloader, download_id), ...]}"""

    def _list(path):
        return [_Record(d, i) for d, i in mapping.get(path, [])]

    return _list


class TestCandidateDirs:
    def test_includes_self_and_parents(self):
        dirs = candidate_dirs("/media/gof/btstore/tv/剧名/Season 1", max_up=3)

        assert dirs[0] == os.path.normpath("/media/gof/btstore/tv/剧名/Season 1")
        assert os.path.normpath("/media/gof/btstore/tv") in dirs

    def test_handles_empty(self):
        assert candidate_dirs("") == []
        assert candidate_dirs("   ") == []


class TestLocateDownloadTasks:
    def test_matches_save_path_above_source_dir(self):
        """源文件在种子目录的子目录里时，要向上回溯到 SAVE_PATH 才命中."""
        source = "/media/gof/btstore/tv/某某剧 (2026)/Season 1"
        repo = _repo({os.path.normpath("/media/gof/btstore/tv"): [("qb1", "hash-a")]})

        tasks = locate_download_tasks([{"source_path": source}], repo)

        assert tasks == {"qb1": {"hash-a"}}

    def test_exact_dir_also_matches(self):
        source = "/downloads/show"
        repo = _repo({os.path.normpath("/downloads/show"): [("qb1", "hash-a")]})

        assert locate_download_tasks([{"source_path": source}], repo) == {"qb1": {"hash-a"}}

    def test_no_match_returns_empty(self):
        repo = _repo({})

        assert locate_download_tasks([{"source_path": "/x/y"}], repo) == {}

    def test_skips_records_without_id(self):
        source = "/downloads/show"
        repo = _repo({os.path.normpath("/downloads/show"): [("qb1", ""), ("qb1", "0"), ("", "hash")]})

        assert locate_download_tasks([{"source_path": source}], repo) == {}

    def test_groups_multiple_downloaders(self):
        source = "/downloads/show"
        repo = _repo(
            {
                os.path.normpath("/downloads/show"): [("qb1", "h1")],
                os.path.normpath("/downloads"): [("tr1", "h2"), ("qb1", "h3")],
            }
        )

        tasks = locate_download_tasks([{"source_path": source}], repo)

        assert tasks == {"qb1": {"h1", "h3"}, "tr1": {"h2"}}

    def test_repo_failure_does_not_raise(self):
        def _boom(path):
            raise RuntimeError("db down")

        assert locate_download_tasks([{"source_path": "/a/b"}], _boom) == {}

    def test_missing_source_path_is_ignored(self):
        repo = _repo({})

        assert locate_download_tasks([{"id": 1}, {}], repo) == {}
