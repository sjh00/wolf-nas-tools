"""迁移 DDL 幂等守卫测试."""

from __future__ import annotations

import sqlalchemy as sa

from app.db.migration_guard import install_idempotent_ddl


class _StubOp:
    """模拟 alembic.op，记录真正下发给数据库的 DDL。"""

    def __init__(self, bind: sa.Connection) -> None:
        self._bind = bind
        self.calls: list[str] = []

    def get_bind(self) -> sa.Connection:
        return self._bind

    def create_table(self, table_name: str, *args, **kwargs) -> None:
        self.calls.append(f"create_table:{table_name}")

    def add_column(self, table_name: str, column: sa.Column, *args, **kwargs) -> None:
        self.calls.append(f"add_column:{table_name}.{column.name}")

    def create_index(self, index_name: str, table_name: str, columns, *args, **kwargs) -> None:
        self.calls.append(f"create_index:{index_name}")

    def create_unique_constraint(self, constraint_name: str, table_name: str, columns, *args, **kwargs) -> None:
        self.calls.append(f"create_unique_constraint:{constraint_name}")

    def create_foreign_key(self, constraint_name: str, source_table: str, referent_table: str, *args, **kwargs) -> None:
        self.calls.append(f"create_foreign_key:{constraint_name}")


def _connect() -> sa.Connection:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text('CREATE TABLE "EXISTING" ("ID" INTEGER PRIMARY KEY, "OLD" TEXT)'))
        conn.execute(sa.text('CREATE INDEX "ix_EXISTING_OLD" ON "EXISTING" ("OLD")'))
    return engine.connect()


def test_install_only_once() -> None:
    conn = _connect()
    with conn:
        op = _StubOp(conn)
        assert install_idempotent_ddl(op) is True
        assert install_idempotent_ddl(op) is False


def test_existing_table_is_skipped() -> None:
    conn = _connect()
    with conn:
        op = _StubOp(conn)
        install_idempotent_ddl(op)
        op.create_table("EXISTING")
        op.create_table("NEW_TABLE")
        assert op.calls == ["create_table:NEW_TABLE"]


def test_existing_column_is_skipped() -> None:
    conn = _connect()
    with conn:
        op = _StubOp(conn)
        install_idempotent_ddl(op)
        op.add_column("EXISTING", sa.Column("OLD", sa.Text()))
        op.add_column("EXISTING", sa.Column("NEW", sa.Text()))
        assert op.calls == ["add_column:EXISTING.NEW"]


def test_existing_index_is_skipped() -> None:
    conn = _connect()
    with conn:
        op = _StubOp(conn)
        install_idempotent_ddl(op)
        op.create_index("ix_EXISTING_OLD", "EXISTING", ["OLD"])
        op.create_index("ix_EXISTING_NEW", "EXISTING", ["NEW"])
        assert op.calls == ["create_index:ix_EXISTING_NEW"]


def test_missing_table_passes_through() -> None:
    conn = _connect()
    with conn:
        op = _StubOp(conn)
        install_idempotent_ddl(op)
        op.add_column("NOT_CREATED_YET", sa.Column("X", sa.Text()))
        op.create_index("ix_OTHER", "NOT_CREATED_YET", ["X"])
        assert op.calls == ["add_column:NOT_CREATED_YET.X", "create_index:ix_OTHER"]
