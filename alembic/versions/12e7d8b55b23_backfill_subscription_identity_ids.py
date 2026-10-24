"""backfill subscription identity ids

Revision ID: 12e7d8b55b23
Revises: 41e4bf75a59e
Create Date: 2026-10-24 13:58:09.296640

"""

# revision identifiers, used by Alembic.
revision = "12e7d8b55b23"
down_revision = "41e4bf75a59e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 数据回填统一由 0d5187136482 执行；保留该版本仅用于历史兼容。
    pass


def downgrade() -> None:
    pass
