"""add media identity tables

Revision ID: eb2e213b5ce3
Revises: 49034daa8419
Create Date: 2026-10-20 09:20:29.903835

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "eb2e213b5ce3"
down_revision = "49034daa8419"
branch_labels = None
depends_on = None


def has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not has_table("MEDIA_IDENTITY"):
        op.create_table(
            "MEDIA_IDENTITY",
            sa.Column("IDENTITY_ID", sa.String(length=26), nullable=False),
            sa.Column("MEDIA_TYPE", sa.String(length=16), nullable=False),
            sa.Column("CONTENT_PROFILE", sa.String(length=64), nullable=False),
            sa.Column("CANONICAL_TITLE", sa.String(length=255), nullable=True),
            sa.Column("YEAR", sa.String(length=8), nullable=True),
            sa.Column("CREATED_AT", sa.DateTime(), nullable=False),
            sa.Column("UPDATED_AT", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("IDENTITY_ID"),
        )
        op.create_index(
            "INDX_MEDIA_IDENTITY_TYPE_PROFILE",
            "MEDIA_IDENTITY",
            ["MEDIA_TYPE", "CONTENT_PROFILE"],
        )

    if not has_table("MEDIA_EXTERNAL_REF"):
        op.create_table(
            "MEDIA_EXTERNAL_REF",
            sa.Column("ID", sa.Integer(), nullable=False),
            sa.Column("IDENTITY_ID", sa.String(length=26), nullable=False),
            sa.Column("PROVIDER", sa.String(length=64), nullable=False),
            sa.Column("EXTERNAL_ID", sa.String(length=255), nullable=False),
            sa.Column("MEDIA_TYPE", sa.String(length=16), nullable=True),
            sa.Column("SCOPE", sa.String(length=64), nullable=False),
            sa.Column("URL", sa.String(length=1024), nullable=True),
            sa.Column("CONFIDENCE", sa.Float(), nullable=False),
            sa.Column("LINK_METHOD", sa.String(length=32), nullable=False),
            sa.Column("LINK_CONFIDENCE", sa.Float(), nullable=False),
            sa.Column("REVIEWED", sa.Integer(), nullable=False),
            sa.Column("IS_PRIMARY", sa.Integer(), nullable=False),
            sa.Column("CREATED_AT", sa.DateTime(), nullable=False),
            sa.Column("UPDATED_AT", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["IDENTITY_ID"], ["MEDIA_IDENTITY.IDENTITY_ID"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("ID"),
            sa.UniqueConstraint("PROVIDER", "EXTERNAL_ID", "SCOPE", name="UQ_MEDIA_EXTERNAL_REF"),
        )
        op.create_index("INDX_MEDIA_EXTERNAL_REF_IDENTITY", "MEDIA_EXTERNAL_REF", ["IDENTITY_ID"])

    if not has_table("MEDIA_METADATA_SNAPSHOT"):
        op.create_table(
            "MEDIA_METADATA_SNAPSHOT",
            sa.Column("ID", sa.Integer(), nullable=False),
            sa.Column("IDENTITY_ID", sa.String(length=26), nullable=False),
            sa.Column("POLICY_KEY", sa.String(length=64), nullable=False),
            sa.Column("CONTENT_PROFILE", sa.String(length=64), nullable=False),
            sa.Column("SNAPSHOT_HASH", sa.String(length=64), nullable=False),
            sa.Column("PAYLOAD", sa.Text(), nullable=False),
            sa.Column("PROVIDERS", sa.Text(), nullable=True),
            sa.Column("STATUS", sa.String(length=32), nullable=False),
            sa.Column("CREATED_AT", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["IDENTITY_ID"], ["MEDIA_IDENTITY.IDENTITY_ID"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("ID"),
        )
        op.create_index("INDX_MEDIA_SNAPSHOT_IDENTITY", "MEDIA_METADATA_SNAPSHOT", ["IDENTITY_ID"])
        op.create_index("INDX_MEDIA_SNAPSHOT_HASH", "MEDIA_METADATA_SNAPSHOT", ["SNAPSHOT_HASH"])

    if not has_table("MEDIA_FIELD_OVERRIDE"):
        op.create_table(
            "MEDIA_FIELD_OVERRIDE",
            sa.Column("ID", sa.Integer(), nullable=False),
            sa.Column("IDENTITY_ID", sa.String(length=26), nullable=False),
            sa.Column("USER_ID", sa.Integer(), nullable=True),
            sa.Column("FIELD_NAME", sa.String(length=128), nullable=False),
            sa.Column("VALUE", sa.Text(), nullable=False),
            sa.Column("PROVIDER", sa.String(length=64), nullable=True),
            sa.Column("EXTERNAL_ID", sa.String(length=255), nullable=True),
            sa.Column("LOCALE", sa.String(length=32), nullable=True),
            sa.Column("LOCKED", sa.Integer(), nullable=False),
            sa.Column("CREATED_AT", sa.DateTime(), nullable=False),
            sa.Column("UPDATED_AT", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["IDENTITY_ID"], ["MEDIA_IDENTITY.IDENTITY_ID"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["USER_ID"], ["RBAC_USERS.ID"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("ID"),
            sa.UniqueConstraint("IDENTITY_ID", "FIELD_NAME", "USER_ID", name="UQ_MEDIA_FIELD_OVERRIDE"),
        )
        op.create_index("INDX_MEDIA_FIELD_OVERRIDE_IDENTITY", "MEDIA_FIELD_OVERRIDE", ["IDENTITY_ID"])


def downgrade() -> None:
    if has_table("MEDIA_FIELD_OVERRIDE"):
        op.drop_index("INDX_MEDIA_FIELD_OVERRIDE_IDENTITY", table_name="MEDIA_FIELD_OVERRIDE")
        op.drop_table("MEDIA_FIELD_OVERRIDE")
    if has_table("MEDIA_METADATA_SNAPSHOT"):
        op.drop_index("INDX_MEDIA_SNAPSHOT_HASH", table_name="MEDIA_METADATA_SNAPSHOT")
        op.drop_index("INDX_MEDIA_SNAPSHOT_IDENTITY", table_name="MEDIA_METADATA_SNAPSHOT")
        op.drop_table("MEDIA_METADATA_SNAPSHOT")
    if has_table("MEDIA_EXTERNAL_REF"):
        op.drop_index("INDX_MEDIA_EXTERNAL_REF_IDENTITY", table_name="MEDIA_EXTERNAL_REF")
        op.drop_table("MEDIA_EXTERNAL_REF")
    if has_table("MEDIA_IDENTITY"):
        op.drop_index("INDX_MEDIA_IDENTITY_TYPE_PROFILE", table_name="MEDIA_IDENTITY")
        op.drop_table("MEDIA_IDENTITY")
