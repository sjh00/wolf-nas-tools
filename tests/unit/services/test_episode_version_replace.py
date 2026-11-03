"""电视剧换版：库中已有该集 + 旧版源已删除 → 用新文件替换。

用户诉求（通用规则，非单次操作）：

    对于电视剧，检测到有新文件了，且库中已有、旧版源文件已删除，
    那么用这个新的替换掉媒体库中旧的。

「旧版源文件已删除」是这里唯一的强信号 —— 用户在 qb 里清掉旧版，
等于认定新版本；而源还在时的重复文件仍然按重复跳过（不误覆盖）。

三条边界必须守住：

1. 旧版源还在 → 跳过（这是普通重复下载，不能覆盖）
2. 新旧大小完全一致 → 跳过（同一份内容被重新处理，覆盖无意义）
3. 库中旧文件已不存在 → 走正常新增，不进入替换
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.domain.mediatypes import MediaType
from app.services.transfer.filetransfer_service import FileTransferService


def _media(mtype=MediaType.TV, season=1, episode=5):
    m = MagicMock()
    m.type = mtype
    m.begin_season = season
    m.begin_episode = episode
    m.end_season = None
    m.end_episode = None
    m.tmdb_id = 12345
    m.title = "示例剧集"
    m.get_season_episode_string.return_value = f"S{season:02d}E{episode:02d}"
    return m


def _service(*, src_size=3 * 1024**3, dest_size=2 * 1024**3):
    svc = FileTransferService.__new__(FileTransferService)
    svc._file_size = lambda path, backend=None: (  # type: ignore[method-assign]
        dest_size if "medialink" in str(path) else src_size
    )
    svc._target_exists = lambda path, backend=None: True  # type: ignore[method-assign]
    return svc


OLD_ROW = SimpleNamespace(
    source_path="/vol6/btstore/tv/Show.S01.1080p",
    dest_path="/vol6/medialink/TV/Show (2026)/Season 1",
    dest_filename="Show - S01E05 - 1080p.mkv",
)


class TestReplaceWhenOldSourceGone:
    def test_replaces_with_different_size(self):
        svc = _service(src_size=4 * 1024**3, dest_size=2 * 1024**3)
        assert (
            svc._should_replace_stale_episode(
                _media(),
                "/vol6/btstore/tv/New/Show.S01E05.2160p.mkv",
                "/vol6/medialink/TV/Show (2026)/Season 1/Show - S01E05.mkv",
                None,
                [OLD_ROW],
            )
            is True
        )

    def test_reason_mentions_old_source_and_sizes(self):
        svc = _service(src_size=4 * 1024**3, dest_size=2 * 1024**3)
        reason = svc._stale_episode_reason(
            _media(),
            "/vol6/btstore/tv/New/Show.S01E05.2160p.mkv",
            "/vol6/medialink/TV/Show (2026)/Season 1/Show - S01E05.mkv",
            None,
            [OLD_ROW],
        )
        assert "Show.S01.1080p" in reason
        assert "2.00G" in reason and "4.00G" in reason


class TestNoReplaceCases:
    def test_same_size_is_duplicate_not_replacement(self):
        """新旧大小一致 = 同一份内容，覆盖只是白白重写."""
        svc = _service(src_size=2 * 1024**3, dest_size=2 * 1024**3)
        assert (
            svc._should_replace_stale_episode(
                _media(), "/src/Show.S01E05.mkv", "/medialink/Show/S01E05.mkv", None, [OLD_ROW]
            )
            is False
        )

    def test_no_stale_row_means_no_replace(self):
        """没有「源已删除」的同集旧记录时，维持原有跳过行为."""
        svc = _service()
        assert (
            svc._should_replace_stale_episode(_media(), "/src/Show.S01E05.mkv", "/medialink/Show/S01E05.mkv", None, [])
            is False
        )

    def test_missing_library_file_means_no_replace(self):
        """库中旧文件已不在 → 应走正常新增，不需要替换."""
        svc = _service()
        svc._target_exists = lambda path, backend=None: False  # type: ignore[method-assign]
        assert (
            svc._should_replace_stale_episode(
                _media(), "/src/Show.S01E05.mkv", "/medialink/Show/S01E05.mkv", None, [OLD_ROW]
            )
            is False
        )

    def test_unknown_source_size_skips(self):
        """拿不到源大小就不冒险覆盖."""
        svc = _service(src_size=0, dest_size=2 * 1024**3)
        assert (
            svc._should_replace_stale_episode(
                _media(), "/src/Show.S01E05.mkv", "/medialink/Show/S01E05.mkv", None, [OLD_ROW]
            )
            is False
        )


class TestStaleDetectionScope:
    """stale_episode_rows 的收集口径：同集 + 目标在 + 源不在."""

    @staticmethod
    def _collect(media, rows, dest_alive_fn, source_alive_fn):
        # 复刻 transfer_media 里的收集逻辑
        dest_alive = [h for h in rows if dest_alive_fn(h)]
        return [
            h
            for h in dest_alive
            if _episode_in_history([h], media.begin_episode)
            and not (getattr(h, "source_path", "") and source_alive_fn(h))
        ]

    def test_only_same_episode(self):
        rows = [
            SimpleNamespace(season_episode="S01E05", source_path="/gone"),
            SimpleNamespace(season_episode="S01E06", source_path="/gone"),
        ]
        media = _media(episode=5)
        out = self._collect(media, rows, lambda h: True, lambda h: False)
        assert len(out) == 1
        assert out[0].season_episode == "S01E05"

    def test_source_still_present_excluded(self):
        rows = [SimpleNamespace(season_episode="S01E05", source_path="/still/here")]
        media = _media(episode=5)
        out = self._collect(media, rows, lambda h: True, lambda h: True)
        assert out == []

    def test_dest_missing_excluded(self):
        rows = [SimpleNamespace(season_episode="S01E05", source_path="/gone")]
        media = _media(episode=5)
        out = self._collect(media, rows, lambda h: False, lambda h: False)
        assert out == []


def _episode_in_history(rows, episode):
    """复刻 _episode_in_history：按 SxxExx 判断该集是否在记录里."""
    import re

    for row in rows:
        text = str(getattr(row, "season_episode", "") or "")
        m = re.search(r"E(\d+)(?:-E(\d+))?", text.upper())
        if not m:
            continue
        begin = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else begin
        if begin <= int(episode) <= end:
            return True
    return False


class TestEpisodeInHistoryHelper:
    """校验上面用于复刻的 helper 与真实语义一致。"""

    @pytest.mark.parametrize(
        ("row_se", "episode", "expected"),
        [
            ("S01E05", 5, True),
            ("S01E05", 6, False),
            ("S01E05-E08", 7, True),
            ("S01E05-E08", 9, False),
            ("S01", 5, False),
            ("", 5, False),
        ],
    )
    def test_semantics(self, row_se, episode, expected):
        row = SimpleNamespace(season_episode=row_se)
        assert _episode_in_history([row], episode) is expected
