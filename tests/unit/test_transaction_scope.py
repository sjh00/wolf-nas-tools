"""显式事务作用域：作用域内所有仓储复用同一 Session，保证原子性。"""

from typing import Any, cast
from unittest.mock import MagicMock

from app.db.session import SessionManager


def _manager_with_factory(session):
    mgr = SessionManager.__new__(SessionManager)
    mgr._engine = cast(Any, object())
    mgr._factory = cast(Any, object())
    # 每个 session_scope()/transaction_scope() 都会 new 一个；这里固定返回同一 fake
    mgr._resolve_factory = lambda: lambda: session  # type: ignore[method-assign]
    return mgr


def test_transaction_scope_shares_single_session():
    session = MagicMock()
    mgr = _manager_with_factory(session)

    with mgr.transaction_scope() as tx:
        assert tx is session
        assert mgr.session is session  # 作用域内 session 属性复用同一对象
        with mgr.session_scope() as inner:
            assert inner is session
        assert session.commit.call_count == 0  # 内层不提交

    session.commit.assert_called_once()  # 仅外层提交
    session.close.assert_called_once()


def test_session_scope_outside_transaction_commits_and_closes():
    session = MagicMock()
    mgr = _manager_with_factory(session)

    with mgr.session_scope() as db:
        assert db is session

    session.commit.assert_called_once()
    session.close.assert_called_once()


def test_transaction_scope_rolls_back_on_error():
    session = MagicMock()
    mgr = _manager_with_factory(session)

    try:
        with mgr.transaction_scope():
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    session.rollback.assert_called_once()
    session.commit.assert_not_called()
    session.close.assert_called_once()
