"""fix subscription keyword ids

Revision ID: 012474971530
Revises: f13d224bd806
Create Date: 2026-10-24 19:03:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "012474971530"
down_revision = "f13d224bd806"
branch_labels = None
depends_on = None


def _column_names(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    for table in ("SUBSCRIBE_MOVIES", "SUBSCRIBE_TVS"):
        if {"KEYWORD", "NAME", "TMDBID"}.issubset(_column_names(table)):
            op.execute(
                sa.text(
                    f"UPDATE `{table}` SET `KEYWORD` = `NAME` "
                    "WHERE `KEYWORD` IS NOT NULL AND `KEYWORD` <> '' "
                    "AND `TMDBID` IS NOT NULL AND `KEYWORD` = `TMDBID`"
                )
            )


def downgrade() -> None:
    # 关键词由 TMDB 数字 ID 修正为媒体标题，属于派生数据，不做回退。
    pass
