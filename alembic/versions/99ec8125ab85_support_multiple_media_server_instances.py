"""support multiple media server instances

Revision ID: 99ec8125ab85
Revises: 0bc1c9053989
Create Date: 2026-10-26 18:23:02.917410

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "99ec8125ab85"
down_revision = "0bc1c9053989"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("MEDIASERVER", sa.Column("TYPE", sa.String(length=32), nullable=False, server_default=""))
    op.execute("UPDATE MEDIASERVER SET TYPE = NAME WHERE TYPE = ''")
    op.add_column("MEDIASYNC_ITEMS", sa.Column("SERVER_ID", sa.Integer(), nullable=True))
    op.add_column("MEDIASYNC_STATISTICS", sa.Column("SERVER_ID", sa.Integer(), nullable=True))
    op.create_index("ix_MEDIASYNC_ITEMS_SERVER_ID", "MEDIASYNC_ITEMS", ["SERVER_ID"])
    op.create_index("ix_MEDIASYNC_STATISTICS_SERVER_ID", "MEDIASYNC_STATISTICS", ["SERVER_ID"])
    op.create_table(
        "MEDIA_LIBRARY_ROUTE",
        sa.Column("ID", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("CONTENT_PROFILE", sa.String(length=64), nullable=False),
        sa.Column("SERVER_ID", sa.Integer(), sa.ForeignKey("MEDIASERVER.ID", ondelete="CASCADE"), nullable=False),
        sa.Column("LIBRARY_ID", sa.String(length=255), nullable=True),
        sa.Column("ENABLED", sa.Boolean(), nullable=False),
        sa.Column("NOTE", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_MEDIA_LIBRARY_ROUTE_CONTENT_PROFILE",
        "MEDIA_LIBRARY_ROUTE",
        ["CONTENT_PROFILE"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_MEDIA_LIBRARY_ROUTE_CONTENT_PROFILE", table_name="MEDIA_LIBRARY_ROUTE")
    op.drop_table("MEDIA_LIBRARY_ROUTE")
    op.drop_index("ix_MEDIASYNC_STATISTICS_SERVER_ID", table_name="MEDIASYNC_STATISTICS")
    op.drop_index("ix_MEDIASYNC_ITEMS_SERVER_ID", table_name="MEDIASYNC_ITEMS")
    op.drop_column("MEDIASYNC_STATISTICS", "SERVER_ID")
    op.drop_column("MEDIASYNC_ITEMS", "SERVER_ID")
    op.drop_column("MEDIASERVER", "TYPE")
