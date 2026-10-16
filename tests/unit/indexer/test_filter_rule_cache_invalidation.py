"""过滤规则缓存失效：变更即时生效 + TTL 兜底（避免改库后必须重启）。"""

import time
from unittest.mock import MagicMock

from app.indexer.core.result_filter import ResultFilter
from app.services.filter_service import FilterService


def _result_filter():
    group = MagicMock()
    group.id = 1002
    group.to_dict.return_value = {"id": 1002, "name": "中字"}
    group_repo = MagicMock()
    group_repo.get_by_id.return_value = group
    rule_repo = MagicMock()
    rule_repo.get_by_group.return_value = []
    rf = ResultFilter(media=MagicMock(), filter_group_repo=group_repo, filter_rule_repo=rule_repo)
    return rf, group_repo, rule_repo


def test_clear_cache_forces_reload():
    rf, group_repo, _rule_repo = _result_filter()
    rf._get_rules(1002)
    rf._get_rules(1002)
    assert group_repo.get_by_id.call_count == 1

    rf.clear_cache()
    rf._get_rules(1002)
    assert group_repo.get_by_id.call_count == 2


def test_ttl_expiry_reloads_without_restart():
    rf, group_repo, _rule_repo = _result_filter()
    rf._rule_cache_ttl = 0.01
    rf._get_rules(1002)
    assert group_repo.get_by_id.call_count == 1

    time.sleep(0.02)
    rf._get_rules(1002)
    assert group_repo.get_by_id.call_count == 2


def test_filter_service_reload_notifies_listeners():
    fs = FilterService(filter_group_repo=MagicMock(), filter_rule_repo=MagicMock(), rg_matcher=MagicMock())
    called = {"n": 0}
    fs.add_change_listener(lambda: called.__setitem__("n", called["n"] + 1))

    fs.reload()

    assert called["n"] == 1
