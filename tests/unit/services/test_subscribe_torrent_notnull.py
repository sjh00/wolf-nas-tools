"""SUBSCRIBE_TORRENTS 的非空列必须被填满。

真实故障：豆瓣榜单订阅报
``NOT NULL constraint failed: SUBSCRIBE_TORRENTS.TYPE``。
「简式插入」只写 TORRENT_NAME/ENCLOSURE，而 TYPE/TITLE/YEAR/SEASON/EPISODE
在库里都是 NOT NULL 且无默认值 —— 这类只用于去重的标记记录因此必然插入失败。
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.db.repositories.subscribe_repository import SubscribeRepository


@pytest.fixture()
def repo(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)

    from contextlib import contextmanager

    @contextmanager
    def _session():
        db = maker()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    repo = SubscribeRepository()
    monkeypatch.setattr(repo, "session", _session)
    return repo, maker


def _types(maker):
    from app.db.models import SubscribeTorrents

    with maker() as db:
        return db.query(SubscribeTorrents).all()


class TestSimpleInsert:
    def test_inserts_without_not_null_violation(self, repo):
        """核心回归：只给名称与空链接也必须能插入。"""
        r, maker = repo
        r.simple_insert_rss_torrent("doubanrank: 示例影片 (DB:[])", None)

        rows = _types(maker)
        assert len(rows) == 1
        row = rows[0]
        assert row.TORRENT_NAME == "doubanrank: 示例影片 (DB:[])"
        assert row.ENCLOSURE is not None

    def test_not_null_text_columns_are_filled(self, repo):
        r, maker = repo
        r.simple_insert_rss_torrent("doubanrank: 示例剧集 (DB:123)", None)

        row = _types(maker)[0]
        for column in ("TYPE", "TITLE", "YEAR", "SEASON", "EPISODE"):
            assert getattr(row, column) == "", f"{column} 必须是空串而不是 None"

    def test_dedup_by_name_still_works(self, repo):
        r, _maker = repo
        r.simple_insert_rss_torrent("doubanrank: 示例影片 (DB:[])", None)
        assert r.get_rss_torrent_by_name("doubanrank: 示例影片 (DB:[])") is not None


class TestFullInsert:
    def test_none_fields_do_not_violate_not_null(self, repo):
        """识别失败时 type/title/year 可能是 None，也不能触发约束失败。"""
        r, maker = repo
        r.insert_rss_torrent(
            torrent_name="Some.Torrent",
            enclosure="http://x/1.torrent",
            type_=None,
            title=None,
            year=None,
            season=None,
            episode=None,
        )

        row = _types(maker)[0]
        assert row.TYPE == ""
        assert row.TITLE == ""
        assert row.YEAR == ""

    def test_real_values_are_preserved(self, repo):
        r, maker = repo
        r.insert_rss_torrent(
            torrent_name="Show.S01E05.1080p",
            enclosure="http://x/2.torrent",
            type_="tv",
            title="示例剧集",
            year="2024",
            season="S01",
            episode="E05",
        )

        row = _types(maker)[0]
        assert (row.TYPE, row.TITLE, row.YEAR, row.SEASON, row.EPISODE) == (
            "tv",
            "示例剧集",
            "2024",
            "S01",
            "E05",
        )


class TestRssProcessorInsert:
    def test_media_without_type_does_not_raise(self, monkeypatch):
        """识别结果没有 type 时不应抛 AttributeError。"""
        from app.media.models import MediaInfo
        from app.services.rss_processor import RssHelper

        captured: dict = {}

        class _Repo:
            def insert(self, **kwargs):
                captured.update(kwargs)

        svc = RssHelper.__new__(RssHelper)
        svc._repo = _Repo()  # type: ignore[assignment]
        svc._cache = type("C", (), {"get": lambda *a: None, "set": lambda *a: None})()  # type: ignore[assignment]
        svc._cache_ttl = 1
        svc.canonicalize_enclosure = staticmethod(lambda url=None: url)  # type: ignore[assignment]

        media = MediaInfo()
        media.org_string = "Some.Torrent"
        media.type = None

        svc.insert_rss_torrents(media)
        assert captured["type_"] == ""
