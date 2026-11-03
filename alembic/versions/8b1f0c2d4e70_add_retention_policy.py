"""add retention policy to transfer history

Revision ID: 8b1f0c2d4e70
Revises: 7c1f4a92b6de
Create Date: 2026-11-03 23:10:00.000000

「旧版本怎么处理」在真实使用里是三种诉求，不能用一个默认行为覆盖：

- keep（默认）     源文件从下载器消失时保留媒体库文件；新版本入库时与旧版并存
- sync_delete      源文件消失时同步删除媒体库文件
- replace          新版本入库成功后删除同作品同季同集的旧版本（洗版）

默认 keep 最安全：qb 里清理种子不应该连累媒体库。
"""

import sqlalchemy as sa

from alembic import op

revision = "8b1f0c2d4e70"
down_revision = "7c1f4a92b6de"
branch_labels = None
depends_on = None

_TABLE = "TRANSFER_HISTORY"
_COLUMN = "RETENTION_POLICY"


def upgrade() -> None:
    # 既有记录一律视为 keep：升级不得改变现有库里任何文件的存留
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column(_COLUMN, sa.String(length=16), nullable=True, server_default="keep"))
    op.create_index(f"ix_{_TABLE}_{_COLUMN}", _TABLE, [_COLUMN])


def downgrade() -> None:
    op.drop_index(f"ix_{_TABLE}_{_COLUMN}", table_name=_TABLE)
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column(_COLUMN)
