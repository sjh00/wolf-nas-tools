"""store agent checkpoint in conversation

Revision ID: b22aae8b0c62
Revises: 915e1cd92e4a
Create Date: 2026-10-27 12:50:21.092874

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b22aae8b0c62"
down_revision = "915e1cd92e4a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("AGENT_CONVERSATION", sa.Column("CHECKPOINT", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("AGENT_CONVERSATION", "CHECKPOINT")
