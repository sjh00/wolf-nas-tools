"""add transfer history files checked at

Revision ID: 007e81318aee
Revises: f09cd92281db
Create Date: 2026-10-29 21:07:53.019534

"""

import sqlalchemy as sa

from alembic import op

revision = "007e81318aee"
down_revision = "f09cd92281db"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if "TRANSFER_HISTORY" not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns("TRANSFER_HISTORY")}


def upgrade() -> None:
    if "FILES_CHECKED_AT" not in _columns():
        op.add_column("TRANSFER_HISTORY", sa.Column("FILES_CHECKED_AT", sa.String(length=20), nullable=True))


def downgrade() -> None:
    if "FILES_CHECKED_AT" in _columns():
        op.drop_column("TRANSFER_HISTORY", "FILES_CHECKED_AT")
