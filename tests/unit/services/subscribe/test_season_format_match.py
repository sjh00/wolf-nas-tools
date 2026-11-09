"""季号写法不一致导致「转移完成 → 订阅进度」永远匹配不到订阅的回归测试。

真实故障链：
- 订阅入库时 SEASON 写的是 `MediaInfo.get_season_string()` 的 `S01` 形式；
- 单集转移完成事件传的是 `get_season_seq()` 的 `1` 形式；
- `get_rss_tv_id` / `update_rss_tv_lack` 直接用 `SEASON == str(season)` 比较，
  两种写法永不相等 → 处理器日志“未找到订阅”，订阅进度永远停在初始值，
  用户看到的现象就是「下载入库了最新 2 集，进度还是 0%」。
"""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models.base import Base
from app.db.models.subscribe import SubscribeTvEpisodes, SubscribeTvs
from app.db.repositories.subscribe_repository import SubscribeRepository
from app.db.session import SessionManager

RSSID = 7
TMDBID = "258348"


@pytest.fixture
def repo_and_mgr():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    mgr = SessionManager()
    mgr._engine = engine
    mgr._factory = sessionmaker(bind=engine, expire_on_commit=False)

    saved = getattr(SubscribeRepository, "_session_manager", None)
    SubscribeRepository._session_manager = mgr
    try:
        yield SubscribeRepository(), mgr
    finally:
        if saved is None:
            try:
                delattr(SubscribeRepository, "_session_manager")
            except AttributeError:
                pass
        else:
            SubscribeRepository._session_manager = saved
        engine.dispose()


def _seed(mgr, season: str = "S02", total: int = 12) -> None:
    with mgr.session_scope() as db:
        db.add(
            SubscribeTvs(
                ID=RSSID,
                NAME="某剧",
                YEAR="2025",
                SEASON=season,
                TMDBID=TMDBID,
                TOTAL_EP=total,
                TOTAL=total,
                CURRENT_EP=1,
                LACK=total,
                STATE="R",
                ADD_DATE=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        )
        db.add(SubscribeTvEpisodes(RSSID=str(RSSID), EPISODES=",".join(str(i) for i in range(1, total + 1))))


def _state(mgr):
    with mgr.session_scope() as db:
        tv = db.query(SubscribeTvs).filter(SubscribeTvs.ID == RSSID).first()
        ep = db.query(SubscribeTvEpisodes).filter(SubscribeTvEpisodes.RSSID == str(RSSID)).first()
        eps = [int(e) for e in (ep.EPISODES or "").split(",") if e.strip().isdigit()]
        return int(tv.LACK or 0), eps


class TestSeasonFormatTolerance:
    @pytest.mark.parametrize("lookup", ["2", "S2", "S02", 2])
    def test_get_id_matches_stored_s01_style(self, repo_and_mgr, lookup):
        repo, mgr = repo_and_mgr
        _seed(mgr, season="S02")
        assert repo.get_rss_tv_id(title="某剧", season=lookup) == RSSID
        assert repo.get_rss_tv_id(title="某剧", season=lookup, tmdbid=TMDBID) == RSSID

    def test_get_id_does_not_match_other_season(self, repo_and_mgr):
        repo, mgr = repo_and_mgr
        _seed(mgr, season="S02")
        assert repo.get_rss_tv_id(title="某剧", season="3") is None
        assert repo.get_rss_tv_id(title="某剧", season="S03") is None

    def test_update_lack_by_title_with_seq_season(self, repo_and_mgr):
        """完成事件按 title/year/season 写入时，季号写法不同也必须命中。"""
        repo, mgr = repo_and_mgr
        _seed(mgr, season="S02")
        repo.update_rss_tv_lack(title="某剧", year="2025", season="2", rssid=None, lack_episodes=[3, 4, 5])
        lack, eps = _state(mgr)
        assert lack == 3
        assert eps == [3, 4, 5]

    def test_update_state_by_title_with_seq_season(self, repo_and_mgr):
        repo, mgr = repo_and_mgr
        _seed(mgr, season="S02")
        repo.update_rss_tv_state(title="某剧", year="2025", season="2", rssid=None, state="S")
        with mgr.session_scope() as db:
            assert db.query(SubscribeTvs).filter(SubscribeTvs.ID == RSSID).first().STATE == "S"

    def test_is_exists_tolerates_season_format(self, repo_and_mgr):
        repo, mgr = repo_and_mgr
        _seed(mgr, season="S02")
        assert repo.is_exists_rss_tv("某剧", "2025", "2") is True
        assert repo.is_exists_rss_tv("某剧", "2025", "3") is False


class TestEpisodeTransferredEndToEnd:
    """真实仓储 + 真实处理器：转移完成必须推进订阅进度。"""

    def test_transfer_updates_lack_and_progress(self, repo_and_mgr, monkeypatch):
        from app.events import Event
        from app.events.constants import MEDIA_EPISODE_TRANSFERRED
        from app.events.payloads import MediaEpisodeTransferredPayload
        from app.services.subscribe import handlers

        repo, mgr = repo_and_mgr
        _seed(mgr, season="S02", total=12)

        # repo_and_mgr ????????????????????????

        handlers.handle_media_episode_transferred(
            Event(
                event_type=MEDIA_EPISODE_TRANSFERRED,
                payload=MediaEpisodeTransferredPayload(
                    tmdb_id=TMDBID, title="某剧", season="2", episodes=[1, 2], total_episodes=12
                ),
            )
        )

        lack, eps = _state(mgr)
        assert eps == list(range(3, 13)), "已入库的 1、2 集必须从缺失集中移除"
        assert lack == 10
        with mgr.session_scope() as db:
            tv = db.query(SubscribeTvs).filter(SubscribeTvs.ID == RSSID).first()
            assert int(tv.CURRENT_EP or 0) == 3, "首个待下载集应推进到 3"
            # 前端进度公式 (total - lack) / total
            assert tv.TOTAL - tv.LACK == 2
