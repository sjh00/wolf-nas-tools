"""split rule id columns

Revision ID: 5ec25bdc842f
Revises: 1dda6a1d4044
Create Date: 2026-07-01 14:50:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5ec25bdc842f"
down_revision: str | None = "1dda6a1d4044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def has_table(table_name):
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return inspector.has_table(table_name)


def has_column(table_name, column_name):
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table(table_name):
        return False
    columns = inspector.get_columns(table_name)
    return any(col["name"] == column_name for col in columns)


def upgrade() -> None:
    if has_table("SITE_BRUSH_TASK") and not has_column("SITE_BRUSH_TASK", "RSS_RULE_ID"):
        op.add_column("SITE_BRUSH_TASK", sa.Column("RSS_RULE_ID", sa.Integer(), nullable=True))
    if has_table("SITE_BRUSH_TASK") and not has_column("SITE_BRUSH_TASK", "REMOVE_RULE_ID"):
        op.add_column("SITE_BRUSH_TASK", sa.Column("REMOVE_RULE_ID", sa.Integer(), nullable=True))
    if has_table("SITE_BRUSH_TASK") and not has_column("SITE_BRUSH_TASK", "STOP_RULE_ID"):
        op.add_column("SITE_BRUSH_TASK", sa.Column("STOP_RULE_ID", sa.Integer(), nullable=True))
    if not has_table("SITE_BRUSH_TASK"):
        return
    existing = {
        tuple(fk.get("constrained_columns") or [])
        for fk in sa.inspect(op.get_bind()).get_foreign_keys("SITE_BRUSH_TASK")
    }
    fks = [
        ("fk_site_brush_task_rss_rule_id", ["RSS_RULE_ID"]),
        ("fk_site_brush_task_remove_rule_id", ["REMOVE_RULE_ID"]),
        ("fk_site_brush_task_stop_rule_id", ["STOP_RULE_ID"]),
    ]
    missing = [(name, cols) for name, cols in fks if tuple(cols) not in existing]
    if not missing:
        return
    # SQLite 不支持 ALTER TABLE ADD CONSTRAINT，batch 会重建表；其余库直接加
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("SITE_BRUSH_TASK") as batch:
            for name, cols in missing:
                batch.create_foreign_key(name, "SITE_BRUSH_RULE", cols, ["ID"])
        return
    for name, cols in missing:
        op.create_foreign_key(name, "SITE_BRUSH_TASK", "SITE_BRUSH_RULE", cols, ["ID"])


def downgrade() -> None:
    if not has_table("SITE_BRUSH_TASK"):
        return
    if op.get_bind().dialect.name == "sqlite":
        _downgrade_sqlite()
        return
    existing = {fk["name"] for fk in sa.inspect(op.get_bind()).get_foreign_keys("SITE_BRUSH_TASK")}
    names = [
        n
        for n in (
            "fk_site_brush_task_stop_rule_id",
            "fk_site_brush_task_remove_rule_id",
            "fk_site_brush_task_rss_rule_id",
        )
        if n in existing
    ]
    if names:
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table("SITE_BRUSH_TASK") as batch:
                for n in names:
                    batch.drop_constraint(n, type_="foreignkey")
        else:
            for n in names:
                op.drop_constraint(n, "SITE_BRUSH_TASK", type_="foreignkey")
    if has_column("SITE_BRUSH_TASK", "STOP_RULE_ID"):
        op.drop_column("SITE_BRUSH_TASK", "STOP_RULE_ID")
    if has_column("SITE_BRUSH_TASK", "REMOVE_RULE_ID"):
        op.drop_column("SITE_BRUSH_TASK", "REMOVE_RULE_ID")
    if has_column("SITE_BRUSH_TASK", "RSS_RULE_ID"):
        op.drop_column("SITE_BRUSH_TASK", "RSS_RULE_ID")


def _downgrade_sqlite() -> None:
    """SQLite 不能直接 drop 带外键的列，重建表并保留除规则列外的数据."""
    inspector = sa.inspect(op.get_bind())
    if "SITE_BRUSH_TASK" not in inspector.get_table_names():
        return
    drop_columns = {"RSS_RULE_ID", "REMOVE_RULE_ID", "STOP_RULE_ID"}
    columns = [
        sa.Column(
            column["name"],
            column["type"],
            primary_key=bool(column.get("primary_key")),
            nullable=bool(column.get("nullable", True)),
            server_default=column.get("default"),
        )
        for column in inspector.get_columns("SITE_BRUSH_TASK")
        if column["name"] not in drop_columns
    ]
    tmp_name = "SITE_BRUSH_TASK_MIGRATION_TMP"
    op.create_table(tmp_name, *columns)
    names = ", ".join(f'"{column.name}"' for column in columns)
    op.execute(f'INSERT INTO "{tmp_name}" ({names}) SELECT {names} FROM "SITE_BRUSH_TASK"')
    op.drop_table("SITE_BRUSH_TASK")
    op.rename_table(tmp_name, "SITE_BRUSH_TASK")
    for index in inspector.get_indexes("SITE_BRUSH_TASK"):
        index_columns = [column for column in (index.get("column_names") or []) if column]
        if set(index_columns) & drop_columns or not index_columns:
            continue
        if index.get("name"):
            op.create_index(
                index["name"],
                "SITE_BRUSH_TASK",
                index_columns,
                unique=bool(index.get("unique")),
            )
