"""媒体库刮削插件：默认增量模式与配置迁移."""

from threading import Event
from unittest.mock import MagicMock

from PIL import Image

from app.plugin_framework.builtin_plugins.libraryscraper.backend.plugin import (
    LibraryScraperPlugin,
)


class _Ctx:
    plugin_id = "libraryscraper"

    def __init__(self, config):
        self.config = config
        self.saved = None
        self.jobs = []
        self.logs = []
        self.emitted = []

    def get_config(self):
        return self.config

    def set_all_config(self, config):
        self.config = config
        self.saved = config

    def schedule_cron(self, job_id, func, cron):
        self.jobs.append((job_id, cron))

    def remove_schedule(self, job_id):
        return None

    def info(self, message):
        self.logs.append(message)

    def emit(self, event, data):
        self.emitted.append((event, data))

    def media_service(self):
        return None


def _plugin(ctx):
    plugin = object.__new__(LibraryScraperPlugin)
    plugin.ctx = ctx
    plugin._event = Event()
    return plugin


def test_normalize_config_migrates_old_mode_and_empty_cron():
    ctx = _Ctx({"mode": "no_force", "cron": ""})
    plugin = _plugin(ctx)

    plugin._normalize_config()

    assert ctx.config["mode"] == "repair"
    assert ctx.config["cron"] == "0 8 * * *"
    assert ctx.saved is not None


def test_do_scrape_repairs_only_incomplete_directories(tmp_path):
    item = tmp_path / "library" / "ABC-123"
    item.mkdir(parents=True)
    (item / "ABC-123.mp4").write_bytes(b"x")
    Image.new("RGB", (2, 3), "white").save(item / "poster.jpg")
    (item / "ABC-123.nfo").write_text("<movie><plot></plot></movie>", encoding="utf-8")
    complete = tmp_path / "library" / "ABC-124"
    complete.mkdir(parents=True)
    (complete / "ABC-124.mp4").write_bytes(b"x")
    Image.new("RGB", (600, 800), (200, 30, 30)).save(complete / "poster.jpg")
    (complete / "ABC-124.nfo").write_text(
        "<movie><title>ABC-124</title><plot>ok</plot><actor><name>A</name></actor></movie>", encoding="utf-8"
    )
    ctx = _Ctx(
        {
            "scraper_path": [str(tmp_path / "library")],
            "mode": "",
            "backup_before_repair": False,
        }
    )
    plugin = _plugin(ctx)
    calls = []
    plugin._scraper = MagicMock()
    plugin._scraper.folder_scraper.side_effect = lambda path, exclude_path=None, mode=None: calls.append((path, mode))
    plugin._scraper.profile_media_info.return_value = MagicMock(to_dict=MagicMock(return_value={"title": "ABC-123"}))

    plugin._do_scrape()

    assert calls == [(str(item), "force_all")]
    assert ctx.emitted == [
        (
            "media.library_synced",
            {
                "target_path": str(item / "ABC-123.mp4"),
                "dest": str(item),
                "media_info": {"title": "ABC-123"},
            },
        )
    ]


def test_placeholder_or_actorless_nfo_dir_is_incomplete(tmp_path):
    placeholder = tmp_path / "ABC-125"
    placeholder.mkdir()
    (placeholder / "ABC-125.mp4").write_bytes(b"x")
    Image.new("RGB", (800, 539), "white").save(placeholder / "poster.jpg")
    (placeholder / "ABC-125.nfo").write_text("<movie><plot>ok</plot><actor></actor></movie>", encoding="utf-8")

    files = [name.name for name in placeholder.iterdir()]
    assert LibraryScraperPlugin._is_incomplete_dir(str(placeholder), files) is True


def _incomplete_library(tmp_path, code="ABC-126"):
    item = tmp_path / "library" / code
    item.mkdir(parents=True)
    (item / f"{code}.mp4").write_bytes(b"x")
    Image.new("RGB", (800, 539), "white").save(item / "poster.jpg")
    (item / f"{code}.nfo").write_text("<movie><plot></plot></movie>", encoding="utf-8")
    (item / ".watermark").write_text("legacy", encoding="utf-8")
    return item


def test_repair_backs_up_before_overwrite(tmp_path):
    item = _incomplete_library(tmp_path)
    backups = tmp_path / "backups"
    ctx = _Ctx(
        {
            "scraper_path": [str(tmp_path / "library")],
            "mode": "repair",
            "backup_before_repair": True,
            "backup_path": str(backups),
        }
    )
    plugin = _plugin(ctx)
    plugin._scraper = MagicMock()
    plugin._scraper.profile_media_info.return_value = MagicMock(to_dict=MagicMock(return_value={"title": "ABC-126"}))

    plugin._do_scrape()

    copied = list(backups.rglob("*"))
    names = {path.name for path in copied if path.is_file()}
    assert {"poster.jpg", "ABC-126.nfo", ".watermark"} <= names
    plugin._scraper.folder_scraper.assert_called_once()
    assert plugin._scraper.folder_scraper.call_args.kwargs["path"] == str(item)


def test_repair_batch_limit_and_only_codes(tmp_path):
    first = _incomplete_library(tmp_path, "ABC-127")
    _incomplete_library(tmp_path, "ABC-128")
    calls = []
    ctx = _Ctx(
        {
            "scraper_path": [str(tmp_path / "library")],
            "mode": "repair",
            "backup_before_repair": False,
            "only_codes": "ABC-127",
        }
    )
    plugin = _plugin(ctx)
    plugin._scraper = MagicMock()
    plugin._scraper.folder_scraper.side_effect = lambda **kwargs: calls.append(kwargs)
    plugin._scraper.profile_media_info.return_value = MagicMock(to_dict=MagicMock(return_value={"title": "ABC-127"}))

    plugin._do_scrape()

    assert [item["path"] for item in calls] == [str(first)]


def test_repair_batch_limit_stops_after_configured_count(tmp_path):
    for index in range(3):
        _incomplete_library(tmp_path, f"ABC-20{index}")
    calls = []
    ctx = _Ctx(
        {
            "scraper_path": [str(tmp_path / "library")],
            "mode": "repair",
            "backup_before_repair": False,
            "batch_limit": 2,
        }
    )
    plugin = _plugin(ctx)
    plugin._scraper = MagicMock()
    plugin._scraper.folder_scraper.side_effect = lambda **kwargs: calls.append(kwargs)
    plugin._scraper.profile_media_info.return_value = MagicMock(to_dict=MagicMock(return_value={"title": "ABC"}))

    plugin._do_scrape()

    assert len(calls) == 2


def test_synthetic_landscape_crop_poster_is_incomplete(tmp_path):
    item = tmp_path / "ABC-130"
    item.mkdir()
    (item / "ABC-130.mp4").write_bytes(b"x")
    fanart = Image.new("RGB", (800, 539), (200, 30, 30))
    fanart.save(item / "fanart.jpg")
    width = int(539 * 2 / 3)
    fanart.crop((800 - width, 0, 800, 539)).save(item / "poster.jpg")
    (item / "ABC-130.nfo").write_text(
        "<movie><plot>ok</plot><actor><name>演员</name></actor></movie>",
        encoding="utf-8",
    )

    files = [name.name for name in item.iterdir()]
    assert LibraryScraperPlugin._is_incomplete_dir(str(item), files) is True
