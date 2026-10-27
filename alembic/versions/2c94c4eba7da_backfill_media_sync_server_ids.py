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
    op.execute(
        """
        UPDATE MEDIASYNC_ITEMS
        SET SERVER_ID = COALESCE(
            (SELECT ID FROM MEDIASERVER WHERE IS_DEFAULT = 1 LIMIT 1),
            (SELECT ID FROM MEDIASERVER ORDER BY ID LIMIT 1)
        )
        WHERE SERVER_ID IS NULL
        """
    )
    op.execute(
        """
        UPDATE MEDIASYNC_STATISTICS
        SET SERVER_ID = COALESCE(
            (SELECT ID FROM MEDIASERVER WHERE IS_DEFAULT = 1 LIMIT 1),
            (SELECT ID FROM MEDIASERVER ORDER BY ID LIMIT 1)
        )
        WHERE SERVER_ID IS NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE MEDIASYNC_ITEMS
        SET SERVER_ID = NULL
        WHERE SERVER_ID = (SELECT ID FROM MEDIASERVER WHERE IS_DEFAULT = 1 LIMIT 1)
        """
    )
    op.execute(
        """
        UPDATE MEDIASYNC_STATISTICS
        SET SERVER_ID = NULL
        WHERE SERVER_ID = (SELECT ID FROM MEDIASERVER WHERE IS_DEFAULT = 1 LIMIT 1)
        """
    )
