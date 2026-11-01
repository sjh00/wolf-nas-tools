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


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    for table in _TABLES:
        existing = _columns(table)
        with op.batch_alter_table(table) as batch_op:
            if "PROVIDER" not in existing:
                batch_op.add_column(sa.Column("PROVIDER", sa.String(length=64), nullable=True))
            if "METADATA_REF" not in existing:
                batch_op.add_column(sa.Column("METADATA_REF", sa.String(length=512), nullable=True))


def downgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("METADATA_REF")
            batch_op.drop_column("PROVIDER")
