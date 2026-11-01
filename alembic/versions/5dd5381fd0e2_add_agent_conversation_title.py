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
    q = op.get_bind().dialect.identifier_preparer.quote
    op.execute(
        f"""
        UPDATE {q("AGENT_CONVERSATION")}
        SET {q("TITLE")} = COALESCE((
            SELECT SUBSTR({q("CONTENT")}, 1, 60)
            FROM {q("AGENT_MESSAGE")}
            WHERE {q("AGENT_MESSAGE")}.{q("CONVERSATION_ID")} = {q("AGENT_CONVERSATION")}.{q("ID")}
              AND {q("AGENT_MESSAGE")}.{q("ROLE")} = 'user'
            ORDER BY {q("AGENT_MESSAGE")}.{q("ID")}
            LIMIT 1
        ), '')
        """
    )


def downgrade() -> None:
    op.drop_column("AGENT_CONVERSATION", "TITLE")
