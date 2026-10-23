"""add subscription identity columns

Revision ID: 378fb11464b8
Revises: eb2e213b5ce3
Create Date: 2026-10-20 09:31:22.338627

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "378fb11464b8"
down_revision = "eb2e213b5ce3"
branch_labels = None
depends_on = None

_TABLES = ("SUBSCRIBE_MOVIES", "SUBSCRIBE_TVS")
_COLUMNS = (
    ("IDENTITY_ID", sa.String(length=26)),
    ("ANCHOR_PROVIDER", sa.String(length=64)),
    ("ANCHOR_EXTERNAL_ID", sa.String(length=255)),
    ("CONTENT_PROFILE", sa.String(length=64)),
    ("METADATA_POLICY", sa.String(length=64)),
    ("NAMING_PROFILE", sa.String(length=64)),
)


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    for table in _TABLES:
        existing = _columns(table)
        if not existing:
            continue
        for name, column_type in _COLUMNS:
            if name not in existing:
                op.add_column(table, sa.Column(name, column_type, nullable=True))
        if "IDENTITY_ID" not in existing:
            op.create_index(f"INDX_{table}_IDENTITY", table, ["IDENTITY_ID"])


def downgrade() -> None:
    for table in _TABLES:
        existing = _columns(table)
        if not existing:
            continue
        if "IDENTITY_ID" in existing:
            op.drop_index(f"INDX_{table}_IDENTITY", table_name=table)
        for name, _ in reversed(_COLUMNS):
            if name in existing:
                with op.batch_alter_table(table) as batch_op:
                    batch_op.drop_column(name)
