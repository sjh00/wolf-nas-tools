"""插件默认过滤规则组创建测试."""

from types import SimpleNamespace

from app.services.filter_service import FilterService


class _GroupRepo:
    def __init__(self):
        self.groups = []

    def get_config_filter_group(self, gid=None):
        return self.groups

    def add_filter_group(self, name, default="N"):
        self.groups.append(SimpleNamespace(ID=len(self.groups) + 1, GROUP_NAME=name, IS_DEFAULT=default, NOTE=""))

    def get_filter_groupid_by_name(self, name):
        return next((group.ID for group in self.groups if group.GROUP_NAME == name), 0)


class _RuleRepo:
    def __init__(self):
        self.rules = []

    def get_config_filter_rule(self, groupid=None):
        return self.rules

    def insert_filter_rule(self, item, ruleid=None):
        self.rules.append(
            SimpleNamespace(
                ID=len(self.rules) + 1,
                GROUP_ID=item["group"],
                ROLE_NAME=item["name"],
                PRIORITY=str(item["pri"]),
                INCLUDE=item["include"],
                EXCLUDE=item["exclude"],
                SIZE_LIMIT=item["size"],
                NOTE=item["free"],
            )
        )


def test_ensure_filter_group_is_idempotent():
    groups = _GroupRepo()
    rules = _RuleRepo()
    service = FilterService(groups, rules, object())  # type: ignore[arg-type]
    seed = [{"name": "one", "pri": 1, "include": "a", "exclude": "b"}]

    assert service.ensure_filter_group("AV 自动优选", seed) == 1
    assert service.ensure_filter_group("AV 自动优选", seed) == 1
    assert len(rules.rules) == 1
    assert rules.rules[0].ROLE_NAME == "one"
