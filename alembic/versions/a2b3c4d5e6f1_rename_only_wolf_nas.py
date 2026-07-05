"""rename ONLY_NEXUS_MEDIA to ONLY_WOLF_NAS

Revision ID: a2b3c4d5e6f1
Revises: a1b2c3d4e5f0
Create Date: 2026-07-05 19:30:00

Rename the ONLY_NEXUS_MEDIA column in DOWNLOADER and
TORRENT_REMOVE_TASK to ONLY_WOLF_NAS.
Provides backward compatibility for databases that still have the old column.
"""

import sqlalchemy as sa
from alembic import op

revision = "a2b3c4d5e6f1"
down_revision = "a1b2c3d4e5f0"
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
    # DOWNLOADER table
    if _has_column("DOWNLOADER", "ONLY_NEXUS_MEDIA") and not _has_column("DOWNLOADER", "ONLY_WOLF_NAS"):
        op.alter_column("DOWNLOADER", "ONLY_NEXUS_MEDIA", new_column_name="ONLY_WOLF_NAS")
    elif not _has_column("DOWNLOADER", "ONLY_WOLF_NAS"):
        op.add_column("DOWNLOADER", sa.Column("ONLY_WOLF_NAS", sa.Integer(), nullable=True))

    # TORRENT_REMOVE_TASK table
    if _has_column("TORRENT_REMOVE_TASK", "ONLY_NEXUS_MEDIA") and not _has_column("TORRENT_REMOVE_TASK", "ONLY_WOLF_NAS"):
        op.alter_column("TORRENT_REMOVE_TASK", "ONLY_NEXUS_MEDIA", new_column_name="ONLY_WOLF_NAS")
    elif not _has_column("TORRENT_REMOVE_TASK", "ONLY_WOLF_NAS"):
        op.add_column("TORRENT_REMOVE_TASK", sa.Column("ONLY_WOLF_NAS", sa.Integer(), nullable=True))


def downgrade() -> None:
    if _has_column("DOWNLOADER", "ONLY_WOLF_NAS") and not _has_column("DOWNLOADER", "ONLY_NEXUS_MEDIA"):
        op.alter_column("DOWNLOADER", "ONLY_WOLF_NAS", new_column_name="ONLY_NEXUS_MEDIA")
    if _has_column("TORRENT_REMOVE_TASK", "ONLY_WOLF_NAS") and not _has_column("TORRENT_REMOVE_TASK", "ONLY_NEXUS_MEDIA"):
        op.alter_column("TORRENT_REMOVE_TASK", "ONLY_WOLF_NAS", new_column_name="ONLY_NEXUS_MEDIA")
