"""add media metadata snapshot scope

Revision ID: fa883b4bfc13
Revises: a3c262783aff
Create Date: 2026-10-22 17:10:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "fa883b4bfc13"
down_revision = "a3c262783aff"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    if "MEDIA_METADATA_SNAPSHOT" not in sa.inspect(op.get_bind()).get_table_names():
        return
    if "SCOPE" not in _columns("MEDIA_METADATA_SNAPSHOT"):
        op.add_column(
            "MEDIA_METADATA_SNAPSHOT",
            sa.Column("SCOPE", sa.String(64), nullable=False, server_default="default"),
        )


def downgrade() -> None:
    if "SCOPE" in _columns("MEDIA_METADATA_SNAPSHOT"):
        with op.batch_alter_table("MEDIA_METADATA_SNAPSHOT") as batch_op:
            batch_op.drop_column("SCOPE")
