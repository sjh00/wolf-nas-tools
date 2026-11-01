"""SiteCache 索引器站点配置同步测试."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.sites.site_cache import SiteCache


def _cache(existing_names: list[str], sites: dict[str, str]) -> tuple[SiteCache, MagicMock]:
    repo = MagicMock()
    repo.list_all.return_value = [SimpleNamespace(site_name=name) for name in existing_names]
    cache = SiteCache.__new__(SiteCache)
    cache._indexer_site_config_repo = repo
    cache._site_by_ids = {index: {"name": name} for index, name in enumerate(sites.values())}
    return cache, repo


def test_sync_preserves_existing_enabled_state():
    """新站点补建时不强制 enabled：已有行（含用户关闭的）保持原状，新行走表默认值。"""
    cache, repo = _cache(["Existing", " DISABLED "], {"a": "existing", "b": "disabled", "c": "New"})

    cache._sync_indexer_site_config()

    repo.upsert_site.assert_called_once_with(site_name="New", source="builtin")
    # 不得把 enabled 一起 upsert，否则用户手动关闭搜索的站点会被重新打开
    assert "enabled" not in repo.upsert_site.call_args.kwargs


def test_sync_skips_empty_and_casefold_matches():
    cache, repo = _cache(["Site"], {"a": " site ", "b": ""})

    cache._sync_indexer_site_config()

    repo.upsert_site.assert_not_called()
