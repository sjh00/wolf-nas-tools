"""Free 到期与下载状态联动测试。"""

from typing import cast

from app.domain.entities.brush import BrushTaskState
from app.message import Message
from app.schemas.download import Torrent, TorrentStatus
from app.services.brush.torrent_lifecycle import BrushTorrentLifecycle
from app.sites.site_cache import SiteCache


class _Repo:
    def __init__(self, rows):
        self.rows = rows
        self.pause_reasons: dict[str, str] = {}
        self.events: list[dict] = []

    def get_brushtask_torrents(self, taskid):
        return self.rows

    def update_brushtask_torrent_pause_reason(self, taskid, download_id, reason):
        self.pause_reasons[download_id] = reason

    def insert_brush_event(self, **kwargs):
        self.events.append(kwargs)


class _Downloader:
    def __init__(self, torrents):
        self.torrents = torrents
        self.stopped: list[str] = []
        self.started: list[str] = []

    def get_downloader_conf(self, downloader_id):
        return {"name": "qb"}

    def get_torrents(self, downloader_id, ids):
        return self.torrents

    def stop_torrents(self, downloader_id, ids):
        self.stopped.extend(ids)

    def start_torrents(self, downloader_id, ids):
        self.started.extend(ids)


class _Helper:
    def __init__(self, free=False):
        self.free = free
        self.attr_calls: list[str] = []

    def get_torrent_attr(self, site_info, url, use_cache=True):
        self.attr_calls.append(url)
        return url, {"free": self.free}

    def is_in_time_range(self, time_range=""):
        return True

    def is_in_active_weekdays(self, active_weekdays=""):
        return True


class _Sites:
    def get_sites(self, siteid=None):
        return {"name": "site"}


class _Message:
    def send_brushtask_pause_message(self, **kwargs):
        pass


def _row(download_id, pause_reason=""):
    return type(
        "Row",
        (),
        {
            "DOWNLOAD_ID": download_id,
            "ENCLOSURE": f"https://site/download/{download_id}",
            "PAGE_URL": f"https://site/detail/{download_id}",
            "PAUSE_REASON": pause_reason,
        },
    )()


def _lifecycle(torrents, rows=None, free=False):
    repo = _Repo(rows or [_row(t.id) for t in torrents])
    downloader = _Downloader(torrents)
    helper = _Helper(free=free)
    lifecycle = BrushTorrentLifecycle(
        helper=helper,
        repo=repo,
        downloader=downloader,
        sites=cast(SiteCache, _Sites()),
        message=cast(Message, _Message()),
    )
    return lifecycle, repo, downloader, helper


def _task(stop_rule):
    return {
        "id": 1,
        "name": "刷流",
        "state": BrushTaskState.RUNNING.value,
        "downloader": 1,
        "site_id": 1,
        "stop_rule": stop_rule,
        "sendmessage": "",
    }


def test_free_end_pauses_incomplete_and_marks_pause_reason():
    torrent = Torrent(id="A", name="未完成", progress=0.5, status=TorrentStatus.Downloading)
    lifecycle, repo, downloader, _ = _lifecycle([torrent])

    lifecycle.stop_task_torrents(1, _task({"stopfree": "Y"}))

    assert downloader.stopped == ["A"]
    assert repo.pause_reasons["A"] == "free_end"
    assert repo.events[0]["reason"] == "Free 到期且下载未完成"


def test_free_end_does_not_stop_completed_torrent():
    torrent = Torrent(id="A", name="已完成", progress=1.0, status=TorrentStatus.Uploading)
    lifecycle, _, downloader, helper = _lifecycle([torrent])

    lifecycle.stop_task_torrents(1, _task({"stopfree": "Y"}))

    assert downloader.stopped == []
    assert helper.attr_calls == []


def test_completed_torrent_still_stops_by_ratio():
    torrent = Torrent(id="A", name="已完成", progress=1.0, ratio=2.5, status=TorrentStatus.Uploading)
    lifecycle, repo, downloader, _ = _lifecycle([torrent])

    lifecycle.stop_task_torrents(1, _task({"stopfree": "Y", "ratio": "gt#1"}))

    assert downloader.stopped == ["A"]
    assert repo.pause_reasons["A"] == "rule"
    assert repo.events[0]["reason"] == "分享率"


def test_paused_torrent_is_not_stopped_repeatedly():
    torrent = Torrent(id="A", name="已暂停", progress=0.5, status=TorrentStatus.Paused)
    lifecycle, _, downloader, _ = _lifecycle([torrent])

    lifecycle.stop_task_torrents(1, _task({"stopfree": "Y"}))

    assert downloader.stopped == []


def test_resume_only_free_end_paused_torrents():
    torrents = [
        Torrent(id="A", name="系统暂停", progress=0.5, status=TorrentStatus.Paused),
        Torrent(id="B", name="手动暂停", progress=0.5, status=TorrentStatus.Paused),
    ]
    rows = [_row("A", "free_end"), _row("B", "manual")]
    lifecycle, repo, downloader, _ = _lifecycle(torrents, rows=rows, free=True)

    lifecycle._resume_free_torrents(
        1,
        {},
        "刷流",
        1,
        {"A": "url-a", "B": "url-b"},
        "qb",
        "",
        {"name": "site"},
        {},
        {"A": "free_end", "B": "manual"},
    )

    assert downloader.started == ["A"]
    assert repo.pause_reasons["A"] == ""
    assert "B" not in repo.pause_reasons
