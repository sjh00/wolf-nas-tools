"""自定义 RSS 源在订阅保存时的权限测试。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from api.routers.subscription import _check_site_grants
from app.schemas.auth import UserContext


def _context(can_use=True):
    custom = MagicMock()
    custom.can_use_ref.return_value = can_use
    grants = MagicMock()
    grants.get_visible_sites.return_value = None
    return SimpleNamespace(custom_rss_service=custom, site_grant_service=grants)


def _user():
    return UserContext(user_id=7, username="owner", level=1, permissions=["subscription:manage"])


class TestCustomRssSubscriptionGrants:
    def test_owner_can_select_custom_rss(self):
        assert _check_site_grants(_context(), _user(), {"rss_sites": ["custom_rss:3"]}) == []

    def test_other_users_source_is_denied_even_in_open_policy(self):
        assert _check_site_grants(_context(can_use=False), _user(), {"rss_sites": ["custom_rss:3"]}) == ["custom_rss:3"]

    def test_custom_rss_cannot_be_used_as_search_site(self):
        assert _check_site_grants(_context(), _user(), {"search_sites": ["custom_rss:3"]}) == ["custom_rss:3"]

    def test_missing_service_fails_closed_for_custom_source(self):
        context = SimpleNamespace(custom_rss_service=None, site_grant_service=None)
        assert _check_site_grants(context, _user(), {"rss_sites": ["custom_rss:3"]}) == ["custom_rss:3"]

    def test_builtin_open_policy_is_unchanged(self):
        assert _check_site_grants(_context(), _user(), {"rss_sites": ["siteA"], "search_sites": ["siteB"]}) == []
