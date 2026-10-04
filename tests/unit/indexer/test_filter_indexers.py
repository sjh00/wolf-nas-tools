"""索引器站点过滤 — 「未选择站点」(site=None) 应包含第三方索引器站点.

回归背景：资源搜索页不选站点时，若前端未显式传空数组，后端会套用默认订阅设置的
search_sites，导致第三方索引器站点被排除。这里锁定索引器层的契约：
site=None 不限制；site=[...] 才按名单过滤。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.indexer.indexer import Indexer


class _FakeClient:
    def __init__(self, client_id: str, indexers: list):
        self._id = client_id
        self._indexers = indexers

    def get_client_id(self) -> str:
        return self._id

    def is_enabled(self) -> bool:
        return True

    def get_indexers(self, check: bool = True) -> list:  # noqa: ARG002
        return list(self._indexers)


def _make_indexer(enabled_third_party: list[str] | None = None) -> Indexer:
    indexer = Indexer.__new__(Indexer)
    repo = MagicMock()
    repo.list_enabled_names.return_value = list(enabled_third_party or [])
    indexer._site_config_repo = repo
    indexer.site_grant_service = None
    return indexer


def _names(indexers) -> set[str]:
    return {i.name for i in indexers}


class TestFilterIndexersSiteScope:
    def _builtin(self):
        return _FakeClient("builtin", [SimpleNamespace(name="mteam", pri=0)])

    def _third_party(self, name: str = "jackett-rousi"):
        return _FakeClient("jackett", [SimpleNamespace(name=name, pri=0)])

    def test_none_means_all_sites_including_third_party(self):
        indexer = _make_indexer(["jackett-rousi"])
        builtin = self._builtin()
        third = self._third_party()

        assert _names(indexer._filter_indexers(builtin, filter_args={"site": None})) == {"mteam"}
        assert _names(indexer._filter_indexers(third, filter_args={"site": None})) == {"jackett-rousi"}

    def test_explicit_site_list_filters(self):
        indexer = _make_indexer(["jackett-rousi"])
        third = self._third_party()
        assert indexer._filter_indexers(third, filter_args={"site": ["mteam"]}) == []
        assert _names(indexer._filter_indexers(third, filter_args={"site": ["jackett-rousi"]})) == {"jackett-rousi"}

    def test_third_party_requires_db_enabled_record(self):
        """第三方索引器必须存在于站点配置且启用（与是否选站无关）"""
        indexer = _make_indexer([])  # 无启用记录
        third = self._third_party()
        assert indexer._filter_indexers(third, filter_args={"site": None}) == []
