"""add agent turns and pending actions

Revision ID: 915e1cd92e4a
Revises: 2c94c4eba7da
Create Date: 2026-10-27 09:43:50.170539

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "915e1cd92e4a"
down_revision = "2c94c4eba7da"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "AGENT_TURN",
        sa.Column("ID", sa.String(length=64), primary_key=True),
        sa.Column("USER_ID", sa.String(length=64), nullable=False),
        sa.Column("SESSION_ID", sa.String(length=128), nullable=False),
        sa.Column("STATUS", sa.String(length=32), nullable=False),
        sa.Column("CANCEL_REQUESTED", sa.Boolean(), nullable=False),
        sa.Column("CREATED_AT", sa.DateTime(), nullable=False),
        sa.Column("UPDATED_AT", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_AGENT_TURN_USER_ID", "AGENT_TURN", ["USER_ID"])
    op.create_index("ix_AGENT_TURN_SESSION_ID", "AGENT_TURN", ["SESSION_ID"])
    op.create_table(
        "AGENT_PENDING_ACTION",
        sa.Column("ID", sa.String(length=64), primary_key=True),
        sa.Column("TURN_ID", sa.String(length=64), sa.ForeignKey("AGENT_TURN.ID", ondelete="CASCADE"), nullable=False),
        sa.Column("USER_ID", sa.String(length=64), nullable=False),
        sa.Column("TOOL", sa.String(length=128), nullable=False),
        sa.Column("ARGUMENTS", sa.JSON(), nullable=False),
        sa.Column("MESSAGE", sa.Text(), nullable=False),
        sa.Column("STATUS", sa.String(length=32), nullable=False),
        sa.Column("CREATED_AT", sa.DateTime(), nullable=False),
        sa.Column("EXPIRES_AT", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_AGENT_PENDING_ACTION_TURN_ID", "AGENT_PENDING_ACTION", ["TURN_ID"])
    op.create_index("ix_AGENT_PENDING_ACTION_USER_ID", "AGENT_PENDING_ACTION", ["USER_ID"])


def downgrade() -> None:
    op.drop_index("ix_AGENT_PENDING_ACTION_USER_ID", table_name="AGENT_PENDING_ACTION")
    op.drop_index("ix_AGENT_PENDING_ACTION_TURN_ID", table_name="AGENT_PENDING_ACTION")
    op.drop_table("AGENT_PENDING_ACTION")
    op.drop_index("ix_AGENT_TURN_SESSION_ID", table_name="AGENT_TURN")
    op.drop_index("ix_AGENT_TURN_USER_ID", table_name="AGENT_TURN")
    op.drop_table("AGENT_TURN")
