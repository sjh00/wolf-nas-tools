"""backfill media sync server ids

Revision ID: 2c94c4eba7da
Revises: bbad71fe1c78
Create Date: 2026-10-27 08:18:12.756564

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "2c94c4eba7da"
down_revision = "bbad71fe1c78"
branch_labels = None
depends_on = None


def upgrade() -> None:
    q = op.get_bind().dialect.identifier_preparer.quote
    for table in ("MEDIASYNC_ITEMS", "MEDIASYNC_STATISTICS"):
        op.execute(
            f"UPDATE {q(table)} SET {q('SERVER_ID')} = COALESCE("
            f"(SELECT {q('ID')} FROM {q('MEDIASERVER')} WHERE {q('IS_DEFAULT')} = 1 LIMIT 1),"
            f"(SELECT {q('ID')} FROM {q('MEDIASERVER')} ORDER BY {q('ID')} LIMIT 1)) "
            f"WHERE {q('SERVER_ID')} IS NULL"
        )


def downgrade() -> None:
    q = op.get_bind().dialect.identifier_preparer.quote
    for table in ("MEDIASYNC_ITEMS", "MEDIASYNC_STATISTICS"):
        op.execute(
            f"UPDATE {q(table)} SET {q('SERVER_ID')} = NULL "
            f"WHERE {q('SERVER_ID')} = (SELECT {q('ID')} FROM {q('MEDIASERVER')} "
            f"WHERE {q('IS_DEFAULT')} = 1 LIMIT 1)"
        )
