"""Sukebei 与 M-Team adult 模式配置回归."""

from __future__ import annotations

import json
from pathlib import Path


def test_sukebei_mirrors_nyaa_layout():
    nyaa = json.loads(Path("config/sites/html/nyaa.json").read_text(encoding="utf-8"))
    sukebei = json.loads(Path("config/sites/html/sukebei.json").read_text(encoding="utf-8"))
    assert sukebei["domain"] == "https://sukebei.nyaa.si"
    assert sukebei["html"]["torrents"] == nyaa["html"]["torrents"]
    assert sukebei["html"]["search"] == nyaa["html"]["search"]


def test_mteam_has_adult_mode_mapping():
    config = json.loads(Path("config/sites/api/mteam.json").read_text(encoding="utf-8"))
    assert config["api"]["endpoints"]["search"]["mode_mapping"]["ADULT"] == "adult"


def test_adult_profile_sets_mteam_adult_mode():
    from types import SimpleNamespace

    from app.sites.api_searcher import ApiSiteSearcher

    site = SimpleNamespace(
        name="mteam",
        api=SimpleNamespace(
            base_url="https://api.m-team.cc",
            endpoints={
                "search": {
                    "method": "POST",
                    "path": "/api/torrent/search",
                    "body": {"mode": "normal", "keyword": "{keyword}"},
                    "mode_mapping": {"ADULT": "adult", "MOVIE": "movie"},
                }
            },
        ),
    )
    from app.media.metadata import ProviderDescriptor
    from app.media.metadata.registry import registry

    class _AdultProvider:
        descriptor = ProviderDescriptor(
            provider_key="test_adult",
            display_name="Adult",
            content_profiles=frozenset({"adult"}),
            search_mode="ADULT",
        )

    registry.register_provider(_AdultProvider(), plugin_id="test")
    try:
        searcher = object.__new__(ApiSiteSearcher)
        setattr(searcher, "_site", site)
        searcher._auth_tokens = {}
        captured = {}
        searcher._execute_request = lambda *args, **kwargs: captured.update(args[1]) or []
        searcher.search(keyword="SSIS-001", content_profile="adult")
        assert captured["mode"] == "adult"
    finally:
        registry.unregister_provider("test_adult", plugin_id="test")

    captured.clear()
    searcher.search(keyword="SSIS-001", content_profile="default")
    assert captured["mode"] == "normal"

    captured.clear()
    searcher.search(keyword="SSIS-001", content_profile="documentary")
    assert captured["mode"] == "normal"
