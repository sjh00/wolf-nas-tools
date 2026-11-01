"""add brush torrent pause reason

Revision ID: 0bc1c9053989
Revises: ab38765f6972
Create Date: 2026-10-26 16:31:08.162253

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0bc1c9053989"
down_revision = "ab38765f6972"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "SITE_BRUSH_TORRENTS",
        sa.Column("PAUSE_REASON", sa.String(length=32), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("SITE_BRUSH_TORRENTS", "PAUSE_REASON")
