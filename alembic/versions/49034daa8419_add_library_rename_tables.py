"""add library rename tables

Revision ID: 49034daa8419
Revises: e1f2a3b4c5d6
Create Date: 2026-10-18T13:30:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "49034daa8419"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    return any(item.get("name") == index_name for item in sa.inspect(op.get_bind()).get_indexes(table_name))


def upgrade() -> None:
    if not _has_table("LIBRARY_RENAME_JOB"):
        op.create_table(
            "LIBRARY_RENAME_JOB",
            sa.Column("ID", sa.Integer(), primary_key=True),
            sa.Column("PLAN_ID", sa.String(64), nullable=False),
            sa.Column("STATUS", sa.String(32), nullable=False),
            sa.Column("SCOPE", sa.Text(), nullable=False),
            sa.Column("RULE_SNAPSHOT", sa.Text(), nullable=False),
            sa.Column("CREATED_BY", sa.Integer(), nullable=True),
            sa.Column("CREATED_AT", sa.String(20), nullable=False),
            sa.Column("STARTED_AT", sa.String(20), nullable=True),
            sa.Column("FINISHED_AT", sa.String(20), nullable=True),
            sa.Column("TOTAL", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("CHANGED", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("UNCHANGED", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("SKIPPED", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("CONFLICT", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("NEEDS_METADATA", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("FAILED", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("DONE", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ROLLED_BACK", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index("INDX_LIBRARY_RENAME_JOB_STATUS", "LIBRARY_RENAME_JOB", ["STATUS"])
        op.create_index("INDX_LIBRARY_RENAME_JOB_PLAN", "LIBRARY_RENAME_JOB", ["PLAN_ID"], unique=True)

    if not _has_table("LIBRARY_RENAME_ITEM"):
        op.create_table(
            "LIBRARY_RENAME_ITEM",
            sa.Column("ID", sa.Integer(), primary_key=True),
            sa.Column("JOB_ID", sa.Integer(), nullable=False),
            sa.Column("BACKEND_ID", sa.String(64), nullable=False),
            sa.Column("ROOT", sa.String(512), nullable=False),
            sa.Column("OLD_PATH", sa.Text(), nullable=False),
            sa.Column("NEW_PATH", sa.Text(), nullable=True),
            sa.Column("OLD_PATH_HASH", sa.String(64), nullable=False),
            sa.Column("OLD_SIZE", sa.BigInteger(), nullable=True),
            sa.Column("OLD_MTIME", sa.Float(), nullable=True),
            sa.Column("METADATA_SOURCE", sa.String(64), nullable=False),
            sa.Column("METADATA_SNAPSHOT", sa.Text(), nullable=False),
            sa.Column("ACTION", sa.String(32), nullable=False),
            sa.Column("STATUS", sa.String(32), nullable=False),
            sa.Column("DIRECTORY_MOVE_ID", sa.String(64), nullable=True),
            sa.Column("AUX_MOVES", sa.Text(), nullable=True),
            sa.Column("REASON", sa.Text(), nullable=True),
            sa.Column("ERROR", sa.Text(), nullable=True),
            sa.Column("ROLLBACK_STATUS", sa.String(32), nullable=True),
            sa.UniqueConstraint("JOB_ID", "OLD_PATH_HASH", name="UQ_LIBRARY_RENAME_ITEM_PATH"),
        )
        op.create_index("INDX_LIBRARY_RENAME_ITEM_JOB", "LIBRARY_RENAME_ITEM", ["JOB_ID"])
        op.create_index("INDX_LIBRARY_RENAME_ITEM_STATUS", "LIBRARY_RENAME_ITEM", ["STATUS"])

    if not _has_table("LIBRARY_MEDIA_METADATA"):
        op.create_table(
            "LIBRARY_MEDIA_METADATA",
            sa.Column("ID", sa.Integer(), primary_key=True),
            sa.Column("BACKEND_ID", sa.String(64), nullable=False),
            sa.Column("PATH", sa.Text(), nullable=False),
            sa.Column("PATH_HASH", sa.String(64), nullable=False),
            sa.Column("TYPE", sa.String(32), nullable=False),
            sa.Column("TITLE", sa.String(512), nullable=False),
            sa.Column("YEAR", sa.String(16), nullable=False),
            sa.Column("TMDBID", sa.String(64), nullable=False),
            sa.Column("SEASON", sa.String(32), nullable=False),
            sa.Column("EPISODE", sa.String(64), nullable=False),
            sa.Column("SEASON_EPISODE_COUNT", sa.Integer(), nullable=True),
            sa.Column("SOURCE_FILENAME", sa.String(512), nullable=True),
            sa.Column("METADATA_SOURCE", sa.String(64), nullable=False),
            sa.Column("CONFIDENCE", sa.String(16), nullable=False),
            sa.Column("IS_MANUAL", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("FILE_SIZE", sa.BigInteger(), nullable=True),
            sa.Column("FILE_MTIME", sa.Float(), nullable=True),
            sa.Column("RAW", sa.Text(), nullable=True),
            sa.Column("CREATED_AT", sa.String(20), nullable=False),
            sa.Column("UPDATED_AT", sa.String(20), nullable=False),
            sa.Column("UPDATED_BY", sa.Integer(), nullable=True),
            sa.UniqueConstraint("BACKEND_ID", "PATH_HASH", name="UQ_LIBRARY_MEDIA_METADATA_PATH"),
        )
        op.create_index("INDX_LIBRARY_MEDIA_METADATA_PATH", "LIBRARY_MEDIA_METADATA", ["PATH_HASH"])

    if _has_table("TRANSFER_HISTORY") and not _has_index("TRANSFER_HISTORY", "INDX_TRANSFER_HISTORY_DEST"):
        op.create_index(
            "INDX_TRANSFER_HISTORY_DEST",
            "TRANSFER_HISTORY",
            ["DEST_PATH", "DEST_FILENAME"],
        )


def downgrade() -> None:
    if _has_table("TRANSFER_HISTORY") and _has_index("TRANSFER_HISTORY", "INDX_TRANSFER_HISTORY_DEST"):
        op.drop_index("INDX_TRANSFER_HISTORY_DEST", table_name="TRANSFER_HISTORY")
    if _has_table("LIBRARY_MEDIA_METADATA"):
        op.drop_table("LIBRARY_MEDIA_METADATA")
    if _has_table("LIBRARY_RENAME_ITEM"):
        op.drop_table("LIBRARY_RENAME_ITEM")
    if _has_table("LIBRARY_RENAME_JOB"):
        op.drop_table("LIBRARY_RENAME_JOB")
