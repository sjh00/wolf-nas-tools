"""add original_language to filter rules

Revision ID: a1b2c3d4e5f0
Revises: e5efa40afddb
Create Date: 2026-07-05 12:00:00

Add ORIGINAL_LANGUAGE column to CONFIG_FILTER_RULES to support
filtering resources by TMDB original language (zh/en/ja/ko/fr/de/ru/hi/other).
Defaults to empty string (no language constraint).
"""

import sqlalchemy as sa

from alembic import op

revision = "a1b2c3d4e5f0"
down_revision = "e5efa40afddb"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table(table_name):
        return False
    columns = inspector.get_columns(table_name)
    return any(col["name"] == column_name for col in columns)


def upgrade() -> None:
    if not _has_column("CONFIG_FILTER_RULES", "ORIGINAL_LANGUAGE"):
        op.add_column(
            "CONFIG_FILTER_RULES",
            sa.Column("ORIGINAL_LANGUAGE", sa.Text(), nullable=True),
        )
    # Backfill existing rows to empty string so the constraint is uniformly "no language".
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE CONFIG_FILTER_RULES SET ORIGINAL_LANGUAGE = '' WHERE ORIGINAL_LANGUAGE IS NULL"
        )
    )


def downgrade() -> None:
    if _has_column("CONFIG_FILTER_RULES", "ORIGINAL_LANGUAGE"):
        op.drop_column("CONFIG_FILTER_RULES", "ORIGINAL_LANGUAGE")