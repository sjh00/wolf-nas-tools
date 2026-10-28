"""add transfer history poster

Revision ID: c7353b36debb
Revises: 5dd5381fd0e2
Create Date: 2026-10-28 09:17:01.514317

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "c7353b36debb"
down_revision = "5dd5381fd0e2"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns("TRANSFER_HISTORY")}


def upgrade() -> None:
    if "POSTER" not in _columns():
        op.add_column("TRANSFER_HISTORY", sa.Column("POSTER", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    if "POSTER" in _columns():
        op.drop_column("TRANSFER_HISTORY", "POSTER")
