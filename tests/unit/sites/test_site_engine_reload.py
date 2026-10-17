"""SiteEngine：在线站点配置更新后重载与目录优先级。"""

import json
import os
from types import SimpleNamespace

import app.sites.engine as engine_mod
from app.sites.engine import SiteEngine


def _write_site(directory, sid):
    data = {"id": sid, "name": sid.upper(), "domain": f"https://{sid}.example"}
    with open(os.path.join(directory, f"{sid}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f)


def test_reload_picks_up_new_definitions(tmp_path):
    html_dir = tmp_path / "html"
    (tmp_path / "api").mkdir()
    html_dir.mkdir()
    _write_site(html_dir, "alpha")

    engine = SiteEngine(definitions_dir=str(tmp_path))
    assert engine.get_by_id("alpha") is not None

    _write_site(html_dir, "beta")
    assert engine.get_by_id("beta") is None

    engine.reload()
    assert engine.get_by_id("beta") is not None


def test_resolve_definitions_prefers_updated_user_dir(tmp_path, monkeypatch):
    sites_dir = tmp_path / "sites"
    (sites_dir / "api").mkdir(parents=True)
    (sites_dir / "html").mkdir()
    _write_site(sites_dir / "html", "alpha")
    (sites_dir / "version").write_text("v20261017", encoding="utf-8")
    monkeypatch.setattr(engine_mod, "settings", SimpleNamespace(config_path=str(tmp_path)))

    assert SiteEngine._resolve_definitions_dir() == str(sites_dir)


def test_resolve_definitions_ignores_builtin_copy(tmp_path, monkeypatch):
    sites_dir = tmp_path / "sites"
    (sites_dir / "api").mkdir(parents=True)
    (sites_dir / "html").mkdir()
    _write_site(sites_dir / "html", "alpha")
    (sites_dir / "version").write_text("builtin", encoding="utf-8")
    monkeypatch.setattr(engine_mod, "settings", SimpleNamespace(config_path=str(tmp_path)))

    assert SiteEngine._resolve_definitions_dir() == str(SiteEngine._BUILTIN_DEFINITIONS_DIR)
