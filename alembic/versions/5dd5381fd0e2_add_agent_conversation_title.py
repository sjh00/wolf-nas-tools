"""add agent conversation title

Revision ID: 5dd5381fd0e2
Revises: b22aae8b0c62
Create Date: 2026-10-27 13:57:12.324096

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "5dd5381fd0e2"
down_revision = "b22aae8b0c62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "AGENT_CONVERSATION",
        sa.Column("TITLE", sa.String(length=120), nullable=False, server_default=""),
    )
    op.execute(
        """
        UPDATE "AGENT_CONVERSATION"
        SET "TITLE" = COALESCE((
            SELECT SUBSTR("CONTENT", 1, 60)
            FROM "AGENT_MESSAGE"
            WHERE "AGENT_MESSAGE"."CONVERSATION_ID" = "AGENT_CONVERSATION"."ID"
              AND "AGENT_MESSAGE"."ROLE" = 'user'
            ORDER BY "AGENT_MESSAGE"."ID"
            LIMIT 1
        ), '')
        """
    )


def downgrade() -> None:
    op.drop_column("AGENT_CONVERSATION", "TITLE")
