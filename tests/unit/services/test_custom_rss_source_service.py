"""自定义 RSS 源服务测试。"""

from unittest.mock import MagicMock

import pytest

from app.core.exceptions import ServiceError
from app.domain.entities.custom_rss import CustomRssSourceEntity
from app.schemas.auth import SUPERADMIN_ROLE_CODE, UserContext
from app.services.rss_automation.custom_source_service import CustomRssSourceService


@pytest.fixture
def user():
    return UserContext(user_id=7, username="owner", level=1, permissions=["rss:manage"])


@pytest.fixture
def admin():
    return UserContext(
        user_id=1,
        username="admin",
        level=0,
        permissions=["*"],
        role_codes=[SUPERADMIN_ROLE_CODE],
    )


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def service(repo):
    return CustomRssSourceService(repo=repo)


def _entity(**kwargs):
    values = {"id": 3, "user_id": 7, "name": "我的 RSS", "url": "https://example.com/feed.xml"}
    values.update(kwargs)
    return CustomRssSourceEntity(**values)


class TestCustomRssSourceService:
    def test_create_and_mask_secrets(self, service, repo, user):
        repo.create.side_effect = lambda entity: _entity(
            id=4,
            user_id=entity.user_id,
            name=entity.name,
            url=entity.url,
            cookie=entity.cookie,
            headers=entity.headers,
        )
        result = service.create(
            {
                "name": " 动漫更新 ",
                "url": "https://example.com/rss",
                "cookie": "uid=1",
                "headers": '{"Authorization":"Bearer token"}',
            },
            user,
        )
        assert result["ref"] == "custom_rss:4"
        assert result["cookie"] == "******"
        assert result["headers"] == "******"
        assert repo.create.call_args.args[0].user_id == 7

    def test_update_mask_preserves_existing_secret(self, service, repo, user):
        entity = _entity(cookie="uid=1", headers='{"X-Key":"abc"}')
        repo.get.return_value = entity
        service.update(3, {"name": "新名称", "cookie": "******", "headers": "******"}, user)
        assert entity.cookie == "uid=1"
        assert entity.headers == '{"X-Key":"abc"}'
        assert entity.name == "新名称"

    def test_invalid_url_and_headers(self, service, user):
        with pytest.raises(ServiceError):
            service.create({"name": "bad", "url": "file:///etc/passwd"}, user)
        with pytest.raises(ServiceError):
            service.create({"name": "bad", "url": "https://example.com", "headers": "[]"}, user)

    def test_visible_sites_uses_stable_ref(self, service, repo, user):
        repo.list.return_value = [_entity(last_error="failed"), _entity(id=4, name="另一个")]
        sites = service.visible_sites(user)
        assert sites[0]["value"] == "custom_rss:3"
        assert sites[0]["permissions"] == ["rss"]
        assert sites[0]["health"] == "error"
        repo.list.assert_called_once_with(user, enabled_only=True)

    def test_can_use_ref_checks_owner_scope(self, service, repo, user):
        repo.get.return_value = None
        assert not service.can_use_ref(user, "custom_rss:99")
        assert not service.can_use_ref(user, "站点A")

    def test_poll_articles_marks_success(self, service, repo):
        repo.get.return_value = _entity()
        service._fetch = MagicMock(return_value=("RSS / Atom", [{"title": "A"}]))
        assert service.poll_articles(3) == [{"title": "A"}]
        repo.mark_fetch.assert_called_once_with(3, 1)

    def test_poll_articles_marks_failure(self, service, repo):
        repo.get.return_value = _entity()
        service._fetch = MagicMock(side_effect=ServiceError("network failed"))
        assert service.poll_articles(3) == []
        assert repo.mark_fetch.call_args.args[:2] == (3, 0)
        assert "network failed" in repo.mark_fetch.call_args.args[2]

    def test_superadmin_can_use_private_source(self, service, repo, admin):
        repo.get.return_value = _entity()
        assert service.can_use_ref(admin, "custom_rss:3")
