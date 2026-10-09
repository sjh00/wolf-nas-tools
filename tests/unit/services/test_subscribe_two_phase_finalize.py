"""订阅两阶段完成回归：下载登记待转移 + 转移定稿 + 失败重开。

背景：下载阶段按真实种子清单判定覆盖并登记“待转移”（不删订阅/不写历史），
转移落盘确认后定稿（写历史、删订阅、通知），转移失败则重开订阅并复位下载历史，
既保证下载阶段判定准确，又避免转移失败被误判为已完成。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.domain.entities.rss import SubscribeState
from app.domain.mediatypes import MediaType
from app.events import Event
from app.events.constants import MEDIA_EPISODE_TRANSFERRED, MEDIA_TRANSFER_FINISHED, TRANSFER_FAIL
from app.events.payloads import (
    MediaEpisodeTransferredPayload,
    MediaTransferFinishedPayload,
    TransferFailPayload,
)
from app.services.subscribe import handlers
from app.services.subscribe.management.finish_service import SubscribeFinishService
from app.services.subscribe.management.service import SubscribeService


def _row():
    return SimpleNamespace(
        NAME="克雷瓦提斯",
        YEAR="2024",
        SEASON="2",
        TMDBID="258348",
        IMAGE="http://img",
        DESC="desc",
        TOTAL=12,
        TOTAL_EP=12,
        CURRENT_EP=1,
        OVER_EDITION=0,
        USER_ID=7,
    )


def test_finalize_tv_by_rssid_writes_history_deletes_and_notifies():
    tv_repo = MagicMock()
    tv_repo.get_all.side_effect = lambda *a, **k: [_row()] if k.get("rssid") else []
    history_repo = MagicMock()
    message = MagicMock()
    bus = MagicMock()
    svc = SubscribeFinishService(MagicMock(), tv_repo, history_repo, message, bus)
    delete_fn = MagicMock()

    svc.finalize_tv_by_rssid(5, MediaType.ANIME, delete_fn)

    history_repo.upsert.assert_called_once()
    assert history_repo.upsert.call_args.kwargs["rtype"] == "tv"
    delete_fn.assert_called_once_with(mtype=MediaType.TV, rssid=5)
    bus.publish.assert_called_once()
    message.send_rss_finished_message.assert_called_once()


def test_finalize_movie_by_rssid_writes_history_deletes():
    movie_repo = MagicMock()
    movie_repo.get_all.return_value = [
        SimpleNamespace(NAME="M", YEAR="2020", TMDBID="9", IMAGE="i", DESC="d", OVER_EDITION=0, USER_ID=3)
    ]
    history = MagicMock()
    message = MagicMock()
    bus = MagicMock()
    svc = SubscribeFinishService(movie_repo, MagicMock(), history, message, bus)
    delete = MagicMock()

    svc.finalize_movie_by_rssid(7, delete)

    history.upsert.assert_called_once()
    delete.assert_called_once_with(mtype=MediaType.MOVIE, rssid=7)
    bus.publish.assert_called_once()
    message.send_rss_finished_message.assert_called_once()


def test_episode_transferred_finalizes_only_when_lack_empty():
    tv_repo = MagicMock()
    tv_repo.get_id.return_value = 42
    ep_repo = MagicMock()
    ep_repo.get.return_value = [1, 2, 3]
    finalize = MagicMock()
    event = Event(
        event_type=MEDIA_EPISODE_TRANSFERRED,
        payload=MediaEpisodeTransferredPayload(
            tmdb_id="1", title="T", season="1", episodes=[1, 2, 3], total_episodes=3
        ),
    )
    with (
        patch.object(handlers, "SubscribeTvRepositoryAdapter", return_value=tv_repo),
        patch.object(handlers, "SubscribeTvEpisodeRepositoryAdapter", return_value=ep_repo),
    ):
        handlers.handle_media_episode_transferred(event, finalize_fn=finalize)
    finalize.assert_called_once()
    assert finalize.call_args.args[0] == 42


def test_episode_transferred_partial_does_not_finalize():
    tv_repo = MagicMock()
    tv_repo.get_id.return_value = 42
    ep_repo = MagicMock()
    ep_repo.get.return_value = [1, 2, 3, 4, 5]
    finalize = MagicMock()
    event = Event(
        event_type=MEDIA_EPISODE_TRANSFERRED,
        payload=MediaEpisodeTransferredPayload(tmdb_id="1", title="T", season="1", episodes=[1], total_episodes=5),
    )
    with (
        patch.object(handlers, "SubscribeTvRepositoryAdapter", return_value=tv_repo),
        patch.object(handlers, "SubscribeTvEpisodeRepositoryAdapter", return_value=ep_repo),
    ):
        handlers.handle_media_episode_transferred(event, finalize_fn=finalize)
    finalize.assert_not_called()
    tv_repo.update_lack.assert_called_once()


def test_pending_subscription_not_reopened_on_partial_transfer():
    """待转移(COMPLETED)订阅在分批转移期间保持完成态，避免被 RSS 重新匹配重复下载。"""
    tv_repo = MagicMock()
    tv_repo.get_id.return_value = 42
    tv_repo.get_all.return_value = [SimpleNamespace(state=SubscribeState.COMPLETED.value)]
    ep_repo = MagicMock()
    ep_repo.get.return_value = [1, 2, 3, 4, 5]
    event = Event(
        event_type=MEDIA_EPISODE_TRANSFERRED,
        payload=MediaEpisodeTransferredPayload(tmdb_id="1", title="T", season="1", episodes=[1], total_episodes=5),
    )
    with (
        patch.object(handlers, "SubscribeTvRepositoryAdapter", return_value=tv_repo),
        patch.object(handlers, "SubscribeTvEpisodeRepositoryAdapter", return_value=ep_repo),
    ):
        handlers.handle_media_episode_transferred(event)

    tv_repo.update_state.assert_not_called()
    tv_repo.update_lack.assert_called_once()


def test_transfer_fail_reopens_subscription_and_resets_history():
    svc = MagicMock()
    handler = handlers.build_transfer_fail_reopen_handler(svc)
    history = SimpleNamespace(tmdb_id="123", season_episode="S01E05", downloader="qb", download_id="t1")
    sub = SimpleNamespace(tmdb_id="123", season="1", id=9)
    ep_repo = MagicMock()
    ep_repo.get.return_value = [7]
    event = Event(event_type=TRANSFER_FAIL, payload=TransferFailPayload(path="/dl/x", count=1, reason="boom"))

    with (
        patch.object(handlers, "DownloadHistoryRepositoryAdapter") as dha,
        patch.object(handlers, "SubscribeTvRepositoryAdapter") as tha,
        patch.object(handlers, "SubscribeTvEpisodeRepositoryAdapter", return_value=ep_repo),
        patch.object(handlers, "SubscribeMovieRepositoryAdapter") as mra,
        patch.object(handlers, "RegexParser") as rp,
    ):
        dha.return_value.get_by_path.return_value = history
        tha.return_value.get_all.return_value = [sub]
        mra.return_value.get_all.return_value = []
        rp.return_value.parse.return_value = SimpleNamespace(season=1, episode=5, end_episode=6)
        handler(event)

    svc.update_rss_state.assert_called_once_with(MediaType.TV, 9, SubscribeState.RUNNING.value)
    # 失败集 5-6 回补缺失（已有 7）
    tha.return_value.update_lack.assert_called_once_with(
        title=None, year=None, season=None, rssid=9, lack_episodes=[5, 6, 7]
    )
    dha.return_value.update_state.assert_called_once_with("qb", "t1", "downloading")


def test_transfer_fail_reopens_movie_subscription():
    svc = MagicMock()
    handler = handlers.build_transfer_fail_reopen_handler(svc)
    history = SimpleNamespace(tmdb_id="55", season_episode="", downloader="qb", download_id="t2")
    movie = SimpleNamespace(id=11, tmdb_id="55")
    event = Event(event_type=TRANSFER_FAIL, payload=TransferFailPayload(path="/dl/m", count=1, reason="boom"))

    with (
        patch.object(handlers, "DownloadHistoryRepositoryAdapter") as dha,
        patch.object(handlers, "SubscribeTvRepositoryAdapter") as tha,
        patch.object(handlers, "SubscribeTvEpisodeRepositoryAdapter"),
        patch.object(handlers, "SubscribeMovieRepositoryAdapter") as mra,
        patch.object(handlers, "RegexParser") as rp,
    ):
        dha.return_value.get_by_path.return_value = history
        tha.return_value.get_all.return_value = []
        mra.return_value.get_all.return_value = [movie]
        rp.return_value.parse.return_value = SimpleNamespace(season=None, episode=None, end_episode=None)
        handler(event)

    svc.update_rss_state.assert_called_once_with(MediaType.MOVIE, 11, SubscribeState.RUNNING.value)


def test_movie_transfer_finished_finalizes_movie_subscription():
    svc = MagicMock()
    handler = handlers.build_movie_transfer_finalize_handler(svc)
    sub = SimpleNamespace(id=11, tmdb_id="55")
    event = Event(
        event_type=MEDIA_TRANSFER_FINISHED,
        payload=MediaTransferFinishedPayload(
            in_path=None,
            file=None,
            target_path=None,
            dest=None,
            media_info={"type": MediaType.MOVIE.value, "tmdb_id": "55"},
        ),
    )
    with patch.object(handlers, "SubscribeMovieRepositoryAdapter") as mra:
        mra.return_value.get_all.return_value = [sub]
        handler(event)

    svc.finalize_movie_by_rssid.assert_called_once_with(11)


def test_movie_transfer_finished_ignores_tv():
    svc = MagicMock()
    handler = handlers.build_movie_transfer_finalize_handler(svc)
    event = Event(
        event_type=MEDIA_TRANSFER_FINISHED,
        payload=MediaTransferFinishedPayload(
            in_path=None,
            file=None,
            target_path=None,
            dest=None,
            media_info={"type": MediaType.TV.value, "tmdb_id": "55"},
        ),
    )
    with patch.object(handlers, "SubscribeMovieRepositoryAdapter") as mra:
        handler(event)

    mra.assert_not_called()
    svc.finalize_movie_by_rssid.assert_not_called()


def test_transfer_fail_reopen_scoped_to_owner():
    """仅回滚失败下载归属用户的订阅，不波及同媒体其他用户。"""
    svc = MagicMock()
    handler = handlers.build_transfer_fail_reopen_handler(svc)
    history = SimpleNamespace(tmdb_id="123", season_episode="", downloader="qb", download_id="t1", user_id=3)
    subs = [
        SimpleNamespace(id=9, tmdb_id="123", season="1", user_id=3),
        SimpleNamespace(id=10, tmdb_id="123", season="1", user_id=4),
    ]
    event = Event(event_type=TRANSFER_FAIL, payload=TransferFailPayload(path="/dl/x", count=1, reason="boom"))

    with (
        patch.object(handlers, "DownloadHistoryRepositoryAdapter") as dha,
        patch.object(handlers, "SubscribeTvRepositoryAdapter") as tha,
        patch.object(handlers, "SubscribeTvEpisodeRepositoryAdapter"),
        patch.object(handlers, "SubscribeMovieRepositoryAdapter") as mra,
        patch.object(handlers, "RegexParser") as rp,
    ):
        dha.return_value.get_by_path.return_value = history
        tha.return_value.get_all.return_value = subs
        mra.return_value.get_all.return_value = []
        rp.return_value.parse.return_value = SimpleNamespace(season=None, episode=None, end_episode=None)
        handler(event)

    svc.update_rss_state.assert_called_once_with(MediaType.TV, 9, SubscribeState.RUNNING.value)


def test_movie_transfer_finished_skips_when_not_in_library():
    """电影未入库（如附加文件先落盘）时不定稿。"""
    svc = MagicMock()
    svc.media_exists.return_value = False
    handler = handlers.build_movie_transfer_finalize_handler(svc)
    event = Event(
        event_type=MEDIA_TRANSFER_FINISHED,
        payload=MediaTransferFinishedPayload(
            in_path=None,
            file=None,
            target_path=None,
            dest=None,
            media_info={"type": MediaType.MOVIE.value, "tmdb_id": "55", "title": "M", "year": "2020"},
        ),
    )
    with patch.object(handlers, "SubscribeMovieRepositoryAdapter") as mra:
        mra.return_value.get_all.return_value = [SimpleNamespace(id=11, tmdb_id="55")]
        handler(event)

    svc.finalize_movie_by_rssid.assert_not_called()


def _svc_for_reconcile():
    svc = SubscribeService.__new__(SubscribeService)
    svc._tv_repo = MagicMock()
    svc._movie_repo = MagicMock()
    svc._download_repo = None
    final_tv = MagicMock()
    final_mv = MagicMock()
    reopen = MagicMock()
    setattr(svc, "finalize_tv_by_rssid", final_tv)
    setattr(svc, "finalize_movie_by_rssid", final_mv)
    setattr(svc, "update_rss_state", reopen)
    return svc, final_tv, final_mv, reopen


def test_reconcile_finalizes_when_library_has_media():
    import datetime

    svc, final_tv, _final_mv, reopen = _svc_for_reconcile()
    tv = SimpleNamespace(id=5, name="T", year="2024", season="1", total=12, tmdb_id="1")
    svc._tv_repo.get_all.return_value = [tv]
    svc._movie_repo.get_all.return_value = []
    setattr(svc, "media_exists", MagicMock(return_value=True))

    svc.reconcile_pending_transfers(now=datetime.datetime(2026, 1, 1))

    final_tv.assert_called_once_with(5, MediaType.TV)
    reopen.assert_not_called()


def test_reconcile_reopens_stale_pending():
    import datetime

    svc, final_tv, _final_mv, reopen = _svc_for_reconcile()
    tv = SimpleNamespace(id=5, name="T", year="2024", season="1", total=12, tmdb_id="1")
    svc._tv_repo.get_all.return_value = [tv]
    svc._movie_repo.get_all.return_value = []
    setattr(svc, "media_exists", MagicMock(return_value=False))
    svc._download_repo = MagicMock()
    svc._download_repo.get_by_tmdb.return_value = [SimpleNamespace(tmdb_id="1", date="2020-01-01 00:00:00")]

    svc.reconcile_pending_transfers(now=datetime.datetime(2026, 1, 1))

    final_tv.assert_not_called()
    reopen.assert_called_once_with(MediaType.TV, 5, SubscribeState.RUNNING.value)


def test_reconcile_leaves_fresh_pending():
    import datetime

    svc, final_tv, _final_mv, reopen = _svc_for_reconcile()
    tv = SimpleNamespace(id=5, name="T", year="2024", season="1", total=12, tmdb_id="1")
    svc._tv_repo.get_all.return_value = [tv]
    svc._movie_repo.get_all.return_value = []
    setattr(svc, "media_exists", MagicMock(return_value=False))
    svc._download_repo = MagicMock()
    now = datetime.datetime(2026, 1, 1, 12, 0, 0)
    svc._download_repo.get_by_tmdb.return_value = [
        SimpleNamespace(tmdb_id="1", date=(now - datetime.timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S"))
    ]

    svc.reconcile_pending_transfers(now=now)

    reopen.assert_not_called()
    final_tv.assert_not_called()
