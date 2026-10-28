"""媒体库刮削插件：默认增量模式与配置迁移."""

from threading import Event
from unittest.mock import MagicMock

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

    assert ctx.config["mode"] == "missing"
    assert ctx.config["cron"] == "0 8 * * *"
    assert ctx.saved is not None


def test_do_scrape_defaults_to_missing_mode():
    ctx = _Ctx({"scraper_path": ["/media/library"], "mode": ""})
    plugin = _plugin(ctx)
    calls = []
    plugin._scraper = MagicMock()
    plugin._scraper.folder_scraper.side_effect = lambda path, exclude_path=None, mode=None: calls.append((path, mode))

    plugin._do_scrape()

    assert calls == [("/media/library", "missing")]
