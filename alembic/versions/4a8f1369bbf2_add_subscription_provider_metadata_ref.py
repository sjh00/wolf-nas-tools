"""add subscription provider metadata ref

Revision ID: 4a8f1369bbf2
Revises: 012474971530
Create Date: 2026-10-24 22:32:10.530353

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "4a8f1369bbf2"
down_revision = "012474971530"
branch_labels = None
depends_on = None

_TABLES = (
    "SUBSCRIBE_MOVIES",
    "SUBSCRIBE_TVS",
    "SUBSCRIBE_HISTORY",
    "SUBSCRIBE_TV_EPISODES",
)


def upgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(sa.Column("PROVIDER", sa.String(length=64), nullable=True))
            batch_op.add_column(sa.Column("METADATA_REF", sa.String(length=512), nullable=True))


def downgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("METADATA_REF")
            batch_op.drop_column("PROVIDER")
