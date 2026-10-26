"""add custom rss sources

Revision ID: ab38765f6972
Revises: 4a8f1369bbf2
Create Date: 2026-10-26 10:31:57.490212

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "ab38765f6972"
down_revision = "4a8f1369bbf2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "CUSTOM_RSS_SOURCE",
        sa.Column("ID", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("USER_ID", sa.Integer(), sa.ForeignKey("RBAC_USERS.ID", ondelete="CASCADE"), nullable=True),
        sa.Column("NAME", sa.String(length=255), nullable=False),
        sa.Column("URL", sa.Text(), nullable=False),
        sa.Column("ENABLED", sa.Boolean(), nullable=False),
        sa.Column("PROXY", sa.Boolean(), nullable=False),
        sa.Column("COOKIE", sa.Text(), nullable=True),
        sa.Column("HEADERS", sa.Text(), nullable=True),
        sa.Column("LAST_FETCH_AT", sa.DateTime(), nullable=True),
        sa.Column("LAST_SUCCESS_AT", sa.DateTime(), nullable=True),
        sa.Column("LAST_ERROR", sa.Text(), nullable=True),
        sa.Column("ITEM_COUNT", sa.Integer(), nullable=False),
        sa.Column("CREATED_AT", sa.DateTime(), nullable=False),
        sa.Column("UPDATED_AT", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_CUSTOM_RSS_SOURCE_USER_ID", "CUSTOM_RSS_SOURCE", ["USER_ID"])
    op.create_index("ix_CUSTOM_RSS_SOURCE_ENABLED", "CUSTOM_RSS_SOURCE", ["ENABLED"])


def downgrade() -> None:
    op.drop_index("ix_CUSTOM_RSS_SOURCE_ENABLED", table_name="CUSTOM_RSS_SOURCE")
    op.drop_index("ix_CUSTOM_RSS_SOURCE_USER_ID", table_name="CUSTOM_RSS_SOURCE")
    op.drop_table("CUSTOM_RSS_SOURCE")
