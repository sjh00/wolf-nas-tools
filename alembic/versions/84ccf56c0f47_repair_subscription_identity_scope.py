"""repair subscription identity scope

Revision ID: 84ccf56c0f47
Revises: 12e7d8b55b23
Create Date: 2026-10-24 14:00:54.463640

"""

# revision identifiers, used by Alembic.
revision = "84ccf56c0f47"
down_revision = "12e7d8b55b23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 数据回填统一由 0d5187136482 执行；保留该版本仅用于历史兼容。
    pass


def downgrade() -> None:
    pass
