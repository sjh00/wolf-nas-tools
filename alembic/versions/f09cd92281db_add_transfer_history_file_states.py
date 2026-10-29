"""add transfer history file states

Revision ID: f09cd92281db
Revises: 517c068dd49f
Create Date: 2026-10-29 20:32:17.184032

"""

import sqlalchemy as sa

from alembic import op

revision = "f09cd92281db"
down_revision = "517c068dd49f"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("SOURCE_STATE", sa.String(length=16)),
    ("SOURCE_DELETED_AT", sa.String(length=20)),
    ("DEST_STATE", sa.String(length=16)),
    ("DEST_DELETED_AT", sa.String(length=20)),
)


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if "TRANSFER_HISTORY" not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns("TRANSFER_HISTORY")}


def upgrade() -> None:
    existing = _columns()
    for name, column_type in _COLUMNS:
        if name not in existing:
            op.add_column("TRANSFER_HISTORY", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    existing = _columns()
    for name, _ in reversed(_COLUMNS):
        if name in existing:
            op.drop_column("TRANSFER_HISTORY", name)
