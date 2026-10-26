"""add directory media library routing

Revision ID: bbad71fe1c78
Revises: 99ec8125ab85
Create Date: 2026-10-26 21:08:47.798459

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "bbad71fe1c78"
down_revision = "99ec8125ab85"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "MEDIA_LIBRARY_ROUTE",
        sa.Column("TARGET_PATH", sa.String(length=1024), nullable=False, server_default=""),
    )
    op.drop_index("ix_MEDIA_LIBRARY_ROUTE_CONTENT_PROFILE", table_name="MEDIA_LIBRARY_ROUTE")
    op.create_index(
        "ix_MEDIA_LIBRARY_ROUTE_CONTENT_PROFILE",
        "MEDIA_LIBRARY_ROUTE",
        ["CONTENT_PROFILE"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_MEDIA_LIBRARY_ROUTE_CONTENT_PROFILE", table_name="MEDIA_LIBRARY_ROUTE")
    op.create_index(
        "ix_MEDIA_LIBRARY_ROUTE_CONTENT_PROFILE",
        "MEDIA_LIBRARY_ROUTE",
        ["CONTENT_PROFILE"],
        unique=True,
    )
    op.drop_column("MEDIA_LIBRARY_ROUTE", "TARGET_PATH")
