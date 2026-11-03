"""删除菜单必须级联清理 RBAC_ROLE_MENUS，否则留下孤儿外键。

真实故障：线上数据 `PRAGMA foreign_key_check` 报了 6 条违规，全部是
RBAC_ROLE_MENUS 指向已删除菜单（menu_id 5、28）的孤儿行。
根因是 delete_menu 只删 RBAC_MENUS 行：bulk delete 不触发 ORM 关系级联，
SQLite 默认也不启用外键约束。
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models.base import Base
from app.db.models.rbac import RBACMenu, RBACRole, role_menus
from app.db.repositories.rbac.rbac_menu_repository import RBACMenuRepository
from app.db.session import SessionManager


@pytest.fixture
def repo_and_mgr():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    mgr = SessionManager()
    mgr._engine = engine
    mgr._factory = sessionmaker(bind=engine, expire_on_commit=False)

    saved = getattr(RBACMenuRepository, "_session_manager", None)
    RBACMenuRepository._session_manager = mgr
    try:
        yield RBACMenuRepository(), mgr, engine
    finally:
        if saved is None:
            try:
                delattr(RBACMenuRepository, "_session_manager")
            except AttributeError:
                pass
        else:
            RBACMenuRepository._session_manager = saved
        engine.dispose()


def _seed(mgr) -> dict[str, int]:
    """建角色 + 父菜单 + 子菜单，并把父子都挂到角色上。"""
    with mgr.session_scope() as db:
        role = RBACRole(ROLE_NAME="管理员", ROLE_CODE="admin", ROLE_LEVEL=1, STATUS=1)
        db.add(role)
        db.flush()
        parent = RBACMenu(MENU_NAME="父菜单", MENU_CODE="Parent", MENU_LEVEL=1, SORT_ORDER=0, STATUS=1, IS_BUILTIN=1)
        child = RBACMenu(
            MENU_NAME="子菜单",
            MENU_CODE="ParentChild",
            PARENT_ID=None,
            MENU_LEVEL=2,
            SORT_ORDER=0,
            STATUS=1,
            IS_BUILTIN=1,
        )
        db.add_all([parent, child])
        db.flush()
        child.PARENT_ID = parent.ID
        db.execute(
            role_menus.insert(),
            [{"role_id": role.ID, "menu_id": parent.ID}, {"role_id": role.ID, "menu_id": child.ID}],
        )
        return {"role": role.ID, "parent": parent.ID, "child": child.ID}


def _orphan_count(engine) -> int:
    with engine.connect() as conn:
        return len(conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall())


def test_delete_parent_removes_child_and_role_links(repo_and_mgr):
    repo, mgr, engine = repo_and_mgr
    ids = _seed(mgr)
    assert _orphan_count(engine) == 0

    assert repo.delete_menu(ids["parent"]) is True

    with mgr.session_scope() as db:
        assert db.query(RBACMenu).filter(RBACMenu.ID == ids["parent"]).first() is None
        assert db.query(RBACMenu).filter(RBACMenu.ID == ids["child"]).first() is None
        links = db.execute(role_menus.select()).fetchall()
        assert links == [], "父子菜单的角色关联都应被清理"
    assert _orphan_count(engine) == 0, "不得残留指向已删除菜单的外键"


def test_delete_child_only_removes_its_own_link(repo_and_mgr):
    repo, mgr, engine = repo_and_mgr
    ids = _seed(mgr)

    assert repo.delete_menu(ids["child"]) is True

    with mgr.session_scope() as db:
        links = db.execute(role_menus.select()).fetchall()
        assert [link.menu_id for link in links] == [ids["parent"]]
        assert db.query(RBACMenu).filter(RBACMenu.ID == ids["parent"]).first() is not None
    assert _orphan_count(engine) == 0


def test_delete_missing_menu_returns_false(repo_and_mgr):
    repo, _mgr, _engine = repo_and_mgr
    assert repo.delete_menu(999999) is False
