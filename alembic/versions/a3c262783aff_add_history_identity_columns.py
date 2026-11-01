"""add history identity columns

Revision ID: a3c262783aff
Revises: b2ae0b3c56ac
Create Date: 2026-10-20 12:05:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "a3c262783aff"
down_revision = "b2ae0b3c56ac"
branch_labels = None
depends_on = None

_TABLES = ("DOWNLOAD_HISTORY", "TRANSFER_HISTORY")
_COLUMNS = (
    ("IDENTITY_ID", sa.String(length=26)),
    ("ANCHOR_PROVIDER", sa.String(length=64)),
    ("ANCHOR_EXTERNAL_ID", sa.String(length=255)),
    ("CONTENT_PROFILE", sa.String(length=64)),
)


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    for table in _TABLES:
        existing = _columns(table)
        for name, column_type in _COLUMNS:
            if name not in existing:
                op.add_column(table, sa.Column(name, column_type, nullable=True))
        if "IDENTITY_ID" not in existing:
            op.create_index(f"ix_{table}_IDENTITY_ID", table, ["IDENTITY_ID"])


def downgrade() -> None:
    for table in _TABLES:
        existing = _columns(table)
        if "IDENTITY_ID" in existing:
            op.drop_index(f"ix_{table}_IDENTITY_ID", table_name=table)
        for name, _ in reversed(_COLUMNS):
            if name in existing:
                with op.batch_alter_table(table) as batch_op:
                    batch_op.drop_column(name)
