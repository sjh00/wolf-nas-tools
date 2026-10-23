"""ADR-025 之前历史数据 → anchor/identity 迁移测试."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.db.models.download import DOWNLOADHISTORY
from app.db.models.library_rename import LIBRARYMEDIAMETADATA
from app.db.models.subscribe import SubscribeMovies, SubscribeTvs
from app.db.repositories.media_identity_repository import MediaIdentityRepository
from app.db.session import SessionManager
from app.services.multisource_migration_service import MultiSourceMigrationService


def _manager(engine):
    manager = SessionManager()
    manager._engine = engine
    manager._factory = sessionmaker(bind=engine, expire_on_commit=False)
    MediaIdentityRepository._session_manager = manager
    MultiSourceMigrationService._session_manager = manager
    return manager


def test_migrates_pre_adr_legacy_ids_and_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/migrate.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    _manager(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(SubscribeMovies(NAME="肖申克", YEAR="1994", TMDBID="278"))
        db.add(SubscribeTvs(NAME="权力的游戏", YEAR="2011", TMDBID="DB:26584183", SEASON="S08", CONTENT_PROFILE=""))
        db.add(SubscribeTvs(NAME="进击的巨人", YEAR="2013", TMDBID="BG:55770", SEASON="S01", CONTENT_PROFILE="anime"))
        db.add(
            LIBRARYMEDIAMETADATA(
                BACKEND_ID="local",
                PATH="/tmp/bgm.mkv",
                PATH_HASH="hash-bgm",
                TYPE="anime",
                TITLE="进击的巨人",
                YEAR="2013",
                TMDBID="BG:55770",
                RAW="{}",
            )
        )
        db.add(
            DOWNLOADHISTORY(
                TITLE="豆瓣下载",
                YEAR="2019",
                TYPE="tv",
                TMDBID="DB:26584183",
                SE="S08",
                VOTE="",
                POSTER="",
                OVERVIEW="",
                TORRENT="",
                ENCLOSURE="",
                SITE="",
                DESC="",
                DOWNLOADER="",
                DOWNLOAD_ID="",
                SAVE_PATH="/tmp/x",
                STATE="done",
                DATE="2026-01-01",
            )
        )
        db.commit()

    service = MultiSourceMigrationService()
    dry = service.run(dry_run=True)
    assert dry.errors == []
    assert dry.updated_subscriptions == 3
    assert MediaIdentityRepository().find_by_ref("douban", "26584183") is None

    first = service.run(dry_run=False)
    assert first.errors == []
    assert first.created_identities == 3
    assert first.updated_metadata == 1
    with Session() as db:
        tmdb_movie = db.query(SubscribeMovies).filter(SubscribeMovies.NAME == "肖申克").one()
        db_tv = db.query(SubscribeTvs).filter(SubscribeTvs.NAME == "权力的游戏").one()
        bgm_tv = db.query(SubscribeTvs).filter(SubscribeTvs.NAME == "进击的巨人").one()
        library = db.query(LIBRARYMEDIAMETADATA).filter(LIBRARYMEDIAMETADATA.PATH == "/tmp/bgm.mkv").one()
        download = db.query(DOWNLOADHISTORY).filter(DOWNLOADHISTORY.TITLE == "豆瓣下载").one()
        assert tmdb_movie.TMDBID == "278"
        assert tmdb_movie.ANCHOR_PROVIDER == "tmdb"
        assert tmdb_movie.ANCHOR_EXTERNAL_ID == "278"
        assert db_tv.TMDBID is None
        assert (db_tv.ANCHOR_PROVIDER, db_tv.ANCHOR_EXTERNAL_ID) == ("douban", "26584183")
        assert db_tv.METADATA_POLICY == "douban_primary"
        assert db_tv.IDENTITY_ID
        assert bgm_tv.TMDBID is None
        assert (bgm_tv.ANCHOR_PROVIDER, bgm_tv.ANCHOR_EXTERNAL_ID) == ("bangumi", "55770")
        assert bgm_tv.CONTENT_PROFILE == "anime"
        assert download.TMDBID == ""
        assert (download.ANCHOR_PROVIDER, download.ANCHOR_EXTERNAL_ID) == ("douban", "26584183")
        assert download.IDENTITY_ID
        assert library.TMDBID == ""
        import json

        raw = json.loads(library.RAW or "{}")
        assert raw["anchor_provider"] == "bangumi"
        assert raw["anchor_external_id"] == "55770"

    second = service.run(dry_run=False)
    assert second.errors == []
    assert second.created_identities == 0
