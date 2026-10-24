"""backfill subscription identity

Revision ID: 41e4bf75a59e
Revises: bf80d0272659
Create Date: 2026-10-24 13:43:56.247857

"""

# revision identifiers, used by Alembic.
revision = "41e4bf75a59e"
down_revision = "bf80d0272659"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 数据回填统一由 0d5187136482 执行；保留该版本仅用于历史兼容。
    pass


def downgrade() -> None:
    pass
