"""unset empty subscribe sites

把订阅站点列里的空列表改回 NULL（= 未设置）。

历史写入把「未设置」和「一个都不选」都存成了 "[]"，导致用户取消全选后，
下一次搜索/编辑又被当成「全部站点」展开。改为用 NULL 表示未设置，空列表
只代表用户主动不选，才能让「取消全选」如实生效。

Revision ID: b7c1d2e3f4a5
Revises: 9b977bbef4b4
Create Date: 2026-11-11 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b7c1d2e3f4a5"
down_revision = "9b977bbef4b4"
branch_labels = None
depends_on = None

_TABLES = ("SUBSCRIBE_TVS", "SUBSCRIBE_MOVIES")
_COLUMNS = ("RSS_SITES", "SEARCH_SITES")


def upgrade() -> None:
    bind = op.get_bind()
    # 用 Core 表达式而不是裸 SQL：MySQL 默认把双引号当字符串，裸 SQL 的标识符
    # 引用会失效；Core 会按方言正确加引号。
    for table_name in _TABLES:
        for column_name in _COLUMNS:
            table = sa.table(table_name, sa.column(column_name, sa.Text))
            column = table.c[column_name]
            bind.execute(
                table.update()
                .where(
                    sa.and_(
                        column.isnot(None),
                        sa.func.trim(column).in_(["", "[]"]),
                    )
                )
                .values({column_name: None})
            )


def downgrade() -> None:
    """不可逆：空列表与未设置合并后无法还原用户原本的选择，保持空操作."""
    return
