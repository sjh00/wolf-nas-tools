"""连载剧总集数增长时，缺失集与订阅进度必须保持正确。

真实故障（用户反馈：下载入库最新 2 集后，订阅进度仍为 0，且不再下载其他集）：

1. 策略层在 TMDB 总集数增加时调用 update_total(rssid, new_total, [新增集])，
   `lack_episodes` 只是**新增集**；而 repository 直接覆盖 EPISODES，
   把「尚未补齐的历史缺失集」整体丢弃 → 订阅从此只认最新集，老集永不回补。

2. 进度显示用 CURRENT_EP 反推 lack = total - current_ep + 1，等价于假设
   「缺失集是 current_ep..total 的连续后缀」。用户从最新集开始看时
   （缺 1..39、已下 40-41）CURRENT_EP 仍是 1，进度被算成 0。
"""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models.base import Base
from app.db.models.subscribe import SubscribeTvEpisodes, SubscribeTvs
from app.db.repositories.subscribe_repository import SubscribeRepository
from app.db.session import SessionManager

RSSID = 1


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


def _create(mgr, total: int, current_ep: int | None = 1) -> None:
    with mgr.session_scope() as db:
        db.add(
            SubscribeTvs(
                ID=RSSID,
                NAME="某连载剧",
                YEAR="2025",
                SEASON="S01",
                TMDBID=123456,
                TOTAL_EP=total,
                TOTAL=total,
                CURRENT_EP=current_ep,
                LACK=total,
                STATE="R",
                ADD_DATE=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        )
        db.add(SubscribeTvEpisodes(RSSID=RSSID, EPISODES=",".join(str(i) for i in range(1, total + 1))))


def _state(mgr) -> tuple[int, object, int, list[int]]:
    with mgr.session_scope() as db:
        tv = db.query(SubscribeTvs).filter(SubscribeTvs.ID == RSSID).first()
        ep = db.query(SubscribeTvEpisodes).filter(SubscribeTvEpisodes.RSSID == RSSID).first()
        eps = [int(e) for e in (ep.EPISODES or "").split(",") if e.strip().isdigit()]
        return int(tv.TOTAL or 0), tv.CURRENT_EP, int(tv.LACK or 0), eps


class TestTotalGrowthKeepsMissing:
    def test_history_missing_preserved_after_growth(self, repo_and_mgr):
        """核心回归：总集数 40→41 时，原有缺失集 1-39 必须保留，只加入 41。"""
        repo, mgr = repo_and_mgr
        _create(mgr, total=40)
        # 用户下载了第 40 集 → 缺失剩 1-39
        repo.update_rss_tv_lack(rssid=RSSID, lack_episodes=list(range(1, 40)))
        assert _state(mgr)[3] == list(range(1, 40))

        # TMDB 总集数增长：策略层只传新增集 [41]
        repo.update_rss_tv_total(rssid=RSSID, total_ep=41, lack_episodes=[41])

        total, current_ep, lack, eps = _state(mgr)
        assert total == 41
        assert eps == list(range(1, 40)) + [41], "历史缺失集不得被新增集覆盖"
        assert lack == 40
        assert current_ep == 1, "首个待下载集仍是最早缺失的那集"

    def test_growth_without_prior_download_keeps_all(self, repo_and_mgr):
        repo, mgr = repo_and_mgr
        _create(mgr, total=40)
        repo.update_rss_tv_total(rssid=RSSID, total_ep=41, lack_episodes=[41])
        _, _, lack, eps = _state(mgr)
        assert eps == list(range(1, 42))
        assert lack == 41

    def test_growth_after_all_downloaded_only_adds_new(self, repo_and_mgr):
        """全部补齐后新增一集：缺失集应恰为新增集。"""
        repo, mgr = repo_and_mgr
        _create(mgr, total=40)
        repo.update_rss_tv_lack(rssid=RSSID, lack_episodes=[])
        assert _state(mgr)[3] == []

        repo.update_rss_tv_total(rssid=RSSID, total_ep=41, lack_episodes=[41])
        _, current_ep, lack, eps = _state(mgr)
        assert eps == [41]
        assert lack == 1
        assert current_ep == 41

    def test_current_ep_tracks_first_missing(self, repo_and_mgr):
        """CURRENT_EP 必须随缺失集更新，否则进度口径会失真。"""
        repo, mgr = repo_and_mgr
        _create(mgr, total=40, current_ep=1)
        repo.update_rss_tv_lack(rssid=RSSID, lack_episodes=list(range(20, 41)))
        assert _state(mgr)[1] == 20

        repo.update_rss_tv_total(rssid=RSSID, total_ep=42, lack_episodes=[41, 42])
        # 合并后首个缺失仍是 20
        assert _state(mgr)[1] == 20


class TestTotalShrinkFiltersOutOfRange:
    def test_missing_beyond_new_total_dropped(self, repo_and_mgr):
        """TMDB 更正总集数变小时，越界集号不应残留在缺失列表中。"""
        repo, mgr = repo_and_mgr
        _create(mgr, total=40)
        repo.update_rss_tv_lack(rssid=RSSID, lack_episodes=list(range(30, 41)))

        repo.update_rss_tv_total(rssid=RSSID, total_ep=35, lack_episodes=[])

        total, _, lack, eps = _state(mgr)
        assert total == 35
        assert eps == list(range(30, 36))
        assert lack == 6


class TestIdempotentGrowth:
    def test_repeated_growth_does_not_duplicate(self, repo_and_mgr):
        repo, mgr = repo_and_mgr
        _create(mgr, total=40)
        repo.update_rss_tv_total(rssid=RSSID, total_ep=41, lack_episodes=[41])
        repo.update_rss_tv_total(rssid=RSSID, total_ep=41, lack_episodes=[41])
        _, _, lack, eps = _state(mgr)
        assert eps == list(range(1, 42))
        assert lack == 41
