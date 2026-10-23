"""add person identity tables

Revision ID: b2ae0b3c56ac
Revises: 378fb11464b8
Create Date: 2026-10-20 11:55:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "b2ae0b3c56ac"
down_revision = "378fb11464b8"
branch_labels = None
depends_on = None


def has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not has_table("PERSON_IDENTITY"):
        op.create_table(
            "PERSON_IDENTITY",
            sa.Column("PERSON_ID", sa.String(length=26), nullable=False),
            sa.Column("CANONICAL_NAME", sa.String(length=255), nullable=False),
            sa.Column("ALIASES", sa.Text(), nullable=True),
            sa.Column("IMAGES", sa.Text(), nullable=True),
            sa.Column("CREATED_AT", sa.DateTime(), nullable=False),
            sa.Column("UPDATED_AT", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("PERSON_ID"),
        )
        op.create_index("INDX_PERSON_IDENTITY_NAME", "PERSON_IDENTITY", ["CANONICAL_NAME"])

    if not has_table("PERSON_EXTERNAL_REF"):
        op.create_table(
            "PERSON_EXTERNAL_REF",
            sa.Column("ID", sa.Integer(), nullable=False),
            sa.Column("PERSON_ID", sa.String(length=26), nullable=False),
            sa.Column("PROVIDER", sa.String(length=64), nullable=False),
            sa.Column("EXTERNAL_ID", sa.String(length=255), nullable=False),
            sa.Column("URL", sa.String(length=1024), nullable=True),
            sa.Column("CREATED_AT", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["PERSON_ID"], ["PERSON_IDENTITY.PERSON_ID"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("ID"),
            sa.UniqueConstraint("PROVIDER", "EXTERNAL_ID", name="UQ_PERSON_EXTERNAL_REF"),
        )
        op.create_index("INDX_PERSON_EXTERNAL_REF_PERSON", "PERSON_EXTERNAL_REF", ["PERSON_ID"])


def downgrade() -> None:
    if has_table("PERSON_EXTERNAL_REF"):
        op.drop_index("INDX_PERSON_EXTERNAL_REF_PERSON", table_name="PERSON_EXTERNAL_REF")
        op.drop_table("PERSON_EXTERNAL_REF")
    if has_table("PERSON_IDENTITY"):
        op.drop_index("INDX_PERSON_IDENTITY_NAME", table_name="PERSON_IDENTITY")
        op.drop_table("PERSON_IDENTITY")
