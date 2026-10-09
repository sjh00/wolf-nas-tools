"""DB 连接池配置与调度任务独立连接池测试."""

from unittest.mock import MagicMock

from app.db import engine as db_engine
from app.db.database_factory import DatabaseFactory


def test_get_int_config_reads_env(monkeypatch):
    monkeypatch.setenv("DATABASE__POOL_SIZE", "33")
    assert DatabaseFactory._get_int_config("pool_size", 20) == 33


def test_get_int_config_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("DATABASE__POOL_SIZE", raising=False)
    fake_settings = MagicMock()
    fake_settings.get.return_value = {"database": {}}
    monkeypatch.setattr("app.db.database_factory.settings", fake_settings)
    assert DatabaseFactory._get_int_config("pool_size", 20) == 20


def test_create_engine_applies_pool_env(monkeypatch):
    monkeypatch.setenv("DATABASE__POOL_SIZE", "33")
    monkeypatch.setenv("DATABASE__MAX_OVERFLOW", "7")
    monkeypatch.setenv("DATABASE__POOL_TIMEOUT", "9")
    captured: dict = {}

    def fake_create_engine(url, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr("app.db.database_factory.create_engine", fake_create_engine)
    monkeypatch.setattr(DatabaseFactory, "_get_config_db_type", staticmethod(lambda: "postgresql"))
    monkeypatch.setattr(DatabaseFactory, "_ensure_database_exists", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(DatabaseFactory, "get_database_url", staticmethod(lambda *a, **k: "postgresql://x"))

    DatabaseFactory.create_engine()

    assert captured["pool_size"] == 33
    assert captured["max_overflow"] == 7
    assert captured["pool_timeout"] == 9


def test_scheduler_engine_context_overrides_and_resets(monkeypatch):
    fake_engine = MagicMock()
    fake_factory = MagicMock(return_value="SESSION")
    monkeypatch.setattr(db_engine, "_SchedulerEngine", fake_engine)
    monkeypatch.setattr(db_engine, "_SchedulerSessionFactory", fake_factory)

    assert db_engine.get_engine_override() is None
    with db_engine.scheduler_engine_context():
        assert db_engine.get_engine() is fake_engine
        assert db_engine.get_session_factory() is fake_factory
    assert db_engine.get_engine_override() is None


def test_session_manager_uses_scheduler_factory(monkeypatch):
    from app.db.session import SessionManager

    fake_sess = MagicMock()
    fake_factory = MagicMock(return_value=fake_sess)
    monkeypatch.setattr(db_engine, "_SchedulerEngine", MagicMock())
    monkeypatch.setattr(db_engine, "_SchedulerSessionFactory", fake_factory)

    mgr = SessionManager.__new__(SessionManager)
    mgr._engine = MagicMock()
    mgr._factory = MagicMock()

    with db_engine.scheduler_engine_context():
        with mgr.session_scope() as session:
            assert session is fake_sess

    mgr._factory.assert_not_called()
