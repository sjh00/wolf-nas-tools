"""add media library route backend

Revision ID: 517c068dd49f
Revises: c7353b36debb
Create Date: 2026-10-28 11:01:55.744661

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "517c068dd49f"
down_revision = "c7353b36debb"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns("MEDIA_LIBRARY_ROUTE")}


def upgrade() -> None:
    if "BACKEND_ID" not in _columns():
        op.add_column(
            "MEDIA_LIBRARY_ROUTE",
            sa.Column("BACKEND_ID", sa.String(length=64), nullable=False, server_default="local"),
        )


def downgrade() -> None:
    if "BACKEND_ID" in _columns():
        op.drop_column("MEDIA_LIBRARY_ROUTE", "BACKEND_ID")
