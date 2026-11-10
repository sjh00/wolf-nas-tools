"""订阅站点选择：取消全选必须如实生效，不能被展开成「全部站点」。

真实故障：在「搜索站点」里把站点全部取消后保存，订阅又变回「全选」——下一次
搜索照样打全部站点。根因是空列表和历史未设置共用同一个存储值 "[]"，所有回退
逻辑都把空列表当成「没配置 → 用全部」。
"""

import pytest

from app.db.repositories import subscribe_repository
from app.domain.entities.rss import SubscribeState
from app.domain.media_types import ProviderMediaType
from app.media.models import MediaInfo
from app.services.subscribe.default_settings import default_setting_key
from app.services.subscribe.management.query_service import _filter_sites, _load_sites
from app.services.subscribe.management.utils import normalize_sites
from app.services.subscribe.strategies.base_search import BaseSearchStrategy


def _tv(title="示例剧集"):
    return MediaInfo(
        type=ProviderMediaType.SERIES,
        title=title,
        year="2026",
        begin_season=1,
        org_string=f"{title}.S01E01.mkv",
        rev_string=f"{title}.S01E01.mkv",
    )


class TestNormalizeSites:
    def test_none_stays_none(self):
        assert normalize_sites(None) is None

    def test_empty_list_stays_empty(self):
        assert normalize_sites([]) == []

    def test_string_is_split_and_trimmed(self):
        assert normalize_sites(" a, b ,, c ") == ["a", "b", "c"]

    def test_empty_string_becomes_empty_list(self):
        assert normalize_sites("") == []


class TestDumpSites:
    def test_none_is_stored_as_null(self):
        assert subscribe_repository._dump_sites(None) is None

    def test_empty_list_is_stored_as_empty_json(self):
        assert subscribe_repository._dump_sites([]) == "[]"

    def test_list_is_stored_as_json(self):
        dumped = subscribe_repository._dump_sites(["a", "b"])
        assert dumped is not None
        assert _load_sites(dumped) == ["a", "b"]


class TestLoadSites:
    def test_null_column_means_unset(self):
        assert _load_sites(None) is None
        assert _load_sites("") is None

    def test_empty_json_means_explicitly_none(self):
        assert _load_sites("[]") == []

    def test_list_is_parsed(self):
        assert _load_sites('["a", "b"]') == ["a", "b"]


class TestFilterSites:
    def test_none_is_preserved(self):
        assert _filter_sites(None, ["a"]) is None

    def test_empty_is_preserved(self):
        assert _filter_sites([], ["a"]) == []

    def test_unknown_sites_are_dropped(self):
        assert _filter_sites(["a", "gone"], ["a"]) == ["a"]


@pytest.fixture()
def strategy():
    """只测站点解析，不初始化真实依赖."""

    class _S(BaseSearchStrategy):
        def __init__(self, system_config):
            self._system_config = system_config

    return _S({"DefaultSubscribeSettingTV": {"search_sites": ["默认站点"]}})


class TestEffectiveSearchSites:
    def test_empty_selection_searches_no_site(self, strategy):
        """核心回归：取消全选后必须搜索零站点，而不是全部站点."""
        sites = strategy._get_effective_search_sites({"search_sites": []}, ProviderMediaType.SERIES)

        assert sites == []

    def test_selected_sites_are_used(self, strategy):
        sites = strategy._get_effective_search_sites(
            {"search_sites": ["站点A", "站点B"]}, ProviderMediaType.SERIES
        )

        assert sites == ["站点A", "站点B"]

    def test_unset_falls_back_to_default_setting(self, strategy):
        sites = strategy._get_effective_search_sites({"search_sites": None}, ProviderMediaType.SERIES)

        assert sites == ["默认站点"]

    def test_unset_without_default_means_all(self):
        class _S(BaseSearchStrategy):
            def __init__(self):
                self._system_config = None

        assert _S()._get_effective_search_sites({"search_sites": None}, ProviderMediaType.SERIES) is None


class _FakeQuery:
    def __init__(self, captured):
        self._captured = captured

    def filter(self, *args, **kwargs):
        return self

    def update(self, fields):
        self._captured.update(fields)
        return 1


class _FakeSession:
    def __init__(self, captured):
        self._captured = captured

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def query(self, *args, **kwargs):
        return _FakeQuery(self._captured)


class TestRepositoryKeepsUnset:
    def test_update_skips_none_sites(self, monkeypatch):
        """update 传 None 时不能写空列表，否则「没动过站点」会被改成零站点."""
        from app.db.repositories.subscribe_repository import SubscribeRepository

        repo = SubscribeRepository()
        captured = {}
        monkeypatch.setattr(repo, "session", lambda: _FakeSession(captured))

        repo.update_rss_movie(rssid=1, search_sites=None, name="新名字")

        assert "SEARCH_SITES" not in captured
        assert captured.get("NAME") == "新名字"

    def test_update_writes_empty_list_when_explicitly_cleared(self, monkeypatch):
        from app.db.repositories.subscribe_repository import SubscribeRepository

        repo = SubscribeRepository()
        captured = {}
        monkeypatch.setattr(repo, "session", lambda: _FakeSession(captured))

        repo.update_rss_movie(rssid=1, search_sites=[])

        assert captured.get("SEARCH_SITES") == "[]"


class TestDefaultSettingKey:  # noqa: D101 - 保持与其他用例一致的类式分组
    def test_user_scope_key_is_stable(self):
        assert default_setting_key(ProviderMediaType.SERIES, "default", 7) == (
            "DefaultSubscribeSettingTV::u7"
        )


class TestSubscribeStateUnchanged:  # noqa: D101
    def test_pending_state_value(self):
        assert SubscribeState.PENDING.value == "D"
