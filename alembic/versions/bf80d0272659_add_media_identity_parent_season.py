"""add media identity parent season

Revision ID: bf80d0272659
Revises: fa883b4bfc13
Create Date: 2026-10-22 17:30:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "bf80d0272659"
down_revision = "fa883b4bfc13"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    if "MEDIA_IDENTITY" not in sa.inspect(op.get_bind()).get_table_names():
        return
    columns = _columns("MEDIA_IDENTITY")
    if "PARENT_IDENTITY_ID" not in columns:
        op.add_column(
            "MEDIA_IDENTITY",
            sa.Column("PARENT_IDENTITY_ID", sa.String(26), nullable=True),
        )
    if "SEASON_NUMBER" not in columns:
        op.add_column(
            "MEDIA_IDENTITY",
            sa.Column("SEASON_NUMBER", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    columns = _columns("MEDIA_IDENTITY")
    with op.batch_alter_table("MEDIA_IDENTITY") as batch_op:
        if "SEASON_NUMBER" in columns:
            batch_op.drop_column("SEASON_NUMBER")
        if "PARENT_IDENTITY_ID" in columns:
            batch_op.drop_column("PARENT_IDENTITY_ID")
