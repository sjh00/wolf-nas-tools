"""迁移分支必须收敛为单 head。

背景：每次合并上游新增迁移，都可能与本地合并版本形成第二个 head，
容器启动时会直接失败（Multiple head revisions），无法升级数据库。
这个错误只在部署时暴露，代价很高 —— 在测试里拦住它。
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]


def _script() -> ScriptDirectory:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def test_single_head() -> None:
    heads = _script().get_heads()
    assert len(heads) == 1, (
        "迁移存在多个 head，部署时 alembic upgrade head 会失败：\n"
        f"  {sorted(heads)}\n"
        "请执行：alembic merge -m \"merge heads\" <head1> <head2>"
    )


def test_merge_revision_reachable_from_head() -> None:
    """head 必须可达全部 revision（防止有孤儿分支没并进来）。"""
    script = _script()
    head = script.get_heads()[0]
    reachable = {rev.revision for rev in script.walk_revisions(base="base", head=head)}
    all_revisions = {rev.revision for rev in script.walk_revisions()}
    missing = sorted(all_revisions - reachable)
    assert not missing, f"以下迁移无法从 head 到达（分支未合并）：{missing}"
