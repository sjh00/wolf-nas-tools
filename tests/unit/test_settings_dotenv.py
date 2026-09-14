"""settings .env 加载与启动引导注入测试."""

import os

from app.core.settings import LogConfig, _apply_bootstrap_env, _load_dotenv
from log._config import _resolve_log_level


def test_log_level_default_is_info():
    """默认日志级别应为 info（与 _resolve_log_level 注释一致），避免静默 debug."""
    assert LogConfig().level == "info"
    assert _resolve_log_level({}) == "INFO"


def _write(tmp_path, text: str) -> str:
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_load_dotenv_parses_without_polluting_environ(tmp_path, monkeypatch):
    monkeypatch.delenv("LOG__LEVEL", raising=False)
    monkeypatch.delenv("NEXUS_MEDIA_CONFIG", raising=False)
    path = _write(
        tmp_path,
        '# comment\nLOG__LEVEL=debug\nNEXUS_MEDIA_CONFIG="/x.yaml"\n\nBADLINE\n',
    )

    values = _load_dotenv(path)

    assert values == {"LOG__LEVEL": "debug", "NEXUS_MEDIA_CONFIG": "/x.yaml"}
    assert "LOG__LEVEL" not in os.environ
    assert "NEXUS_MEDIA_CONFIG" not in os.environ


def test_load_dotenv_missing_file_returns_empty(tmp_path):
    assert _load_dotenv(str(tmp_path / "nope.env")) == {}


def test_apply_bootstrap_injects_bootstrap_and_unknown_keys(monkeypatch):
    for key in ("NEXUS_MEDIA_CONFIG", "NEXUS_SITES_DIR", "LOG__LEVEL"):
        monkeypatch.delenv(key, raising=False)
    fields = {"nexus_media_config": None, "log": None}

    _apply_bootstrap_env(
        {
            "NEXUS_MEDIA_CONFIG": "/x.yaml",
            "NEXUS_SITES_DIR": "/sites",
            "LOG__LEVEL": "debug",
        },
        fields,
    )

    assert os.environ["NEXUS_MEDIA_CONFIG"] == "/x.yaml"
    assert os.environ["NEXUS_SITES_DIR"] == "/sites"
    assert "LOG__LEVEL" not in os.environ


def test_apply_bootstrap_keeps_existing_env(monkeypatch):
    monkeypatch.setenv("NEXUS_MEDIA_DATA", "/existing")

    _apply_bootstrap_env({"NEXUS_MEDIA_DATA": "/from-dotenv"}, {"nexus_media_data": None})

    assert os.environ["NEXUS_MEDIA_DATA"] == "/existing"


def test_apply_bootstrap_injects_sqlite_path_alias(monkeypatch):
    monkeypatch.delenv("DATABASE__SQLITE_PATH", raising=False)

    _apply_bootstrap_env({"DATABASE__SQLITE_PATH": "/tmp/x.db"}, {"database": None})

    assert os.environ["DATABASE__SQLITE_PATH"] == "/tmp/x.db"
