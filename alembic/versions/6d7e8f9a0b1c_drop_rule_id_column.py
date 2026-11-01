"""drop rule id column

Revision ID: 6d7e8f9a0b1c
Revises: 5ec25bdc842f
Create Date: 2026-07-01 14:55:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6d7e8f9a0b1c"
down_revision: str | None = "5ec25bdc842f"
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
    if not (has_table("SITE_BRUSH_TASK") and has_column("SITE_BRUSH_TASK", "RULE_ID")):
        return
    if op.get_bind().dialect.name == "sqlite":
        # 5ec 的 SQLite 重建表已去掉 RULE_ID 外键，这里只剩列。
        op.drop_column("SITE_BRUSH_TASK", "RULE_ID")
        return
    op.drop_constraint("SITE_BRUSH_TASK_ibfk_1", "SITE_BRUSH_TASK", type_="foreignkey")
    op.drop_column("SITE_BRUSH_TASK", "RULE_ID")


def downgrade() -> None:
    pass
