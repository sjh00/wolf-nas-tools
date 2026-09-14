"""MediaLibraryMonitorService 单元测试."""

from unittest.mock import MagicMock

import pytest

from app.services.media_library_monitor import MediaLibraryMonitorService


@pytest.fixture
def monitor():
    media_file = MagicMock()
    svc = MediaLibraryMonitorService(media_file_service=media_file, thread_executor=None)
    svc._media_file = media_file
    return svc


class TestOnMediaFileEvent:
    def test_skips_non_media_ext(self, monitor, monkeypatch):
        """非媒体扩展名不触发刮削"""
        monkeypatch.setattr("app.services.media_library_monitor.settings", _fake_settings(True))
        monitor.on_media_file_event("/tmp/a.txt")
        monitor._media_file.scrap_media_path.assert_not_called()

    def test_scrapes_when_enabled(self, monitor, monkeypatch, tmp_path):
        """刮削开启且有媒体文件 → 触发目录刮削"""
        d = tmp_path / "movie" / "Movie(2020)"
        d.mkdir(parents=True)
        f = d / "Movie.2020.1080p.mkv"
        f.write_text("x")
        monkeypatch.setattr("app.services.media_library_monitor.settings", _fake_settings(True))
        monitor.on_media_file_event(str(f))
        monitor._media_file.scrap_media_path.assert_called_once()
        # 应刮削父目录
        assert monitor._media_file.scrap_media_path.call_args.kwargs["path"] == str(d)

    def test_skips_when_disabled(self, monitor, monkeypatch, tmp_path):
        """刮削关闭 → 不触发刮削"""
        d = tmp_path / "movie" / "Movie(2020)"
        d.mkdir(parents=True)
        f = d / "Movie.2020.1080p.mkv"
        f.write_text("x")
        monkeypatch.setattr("app.services.media_library_monitor.settings", _fake_settings(False))
        monitor.on_media_file_event(str(f))
        monitor._media_file.scrap_media_path.assert_not_called()

    def test_dedup_path(self, monitor, monkeypatch, tmp_path):
        """同一路径短时间内去重，只刮削一次"""
        d = tmp_path / "movie" / "Movie(2020)"
        d.mkdir(parents=True)
        f = d / "Movie.2020.1080p.mkv"
        f.write_text("x")
        monkeypatch.setattr("app.services.media_library_monitor.settings", _fake_settings(True))
        monitor.on_media_file_event(str(f))
        monitor.on_media_file_event(str(f))
        assert monitor._media_file.scrap_media_path.call_count == 1


def _fake_settings(scrape_enabled: bool):
    class _FakeMedia:
        def get(self, key, default=None):
            data = {
                "movie_path": ["/tmp/movie"],
                "tv_path": ["/tmp/tv"],
                "anime_path": ["/tmp/anime"],
                "nfo_poster": scrape_enabled,
            }
            v = data.get(key, default)
            return v if v is not None else default

    class _FakeSettings:
        def get(self, key, default=None):
            if key == "media":
                return _FakeMedia()
            return default

    return _FakeSettings()
