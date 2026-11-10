"""anime layout default category

动漫媒体库目录结构的历史默认值是 flat（平铺），导致动漫作品直接落在库根
（…/medialink/TV/作品 (年份)），跳过分类目录。分类目录明明存在，作品却不在
里面，与「按分类归档」的预期相反。

这里把仍为旧默认值 flat 的配置改成 category。用户显式选择 flat 的场景无法与
旧默认区分，但分类目录是既定用法，统一按分类归档。

Revision ID: c8d9e0f1a2b3
Revises: b7c1d2e3f4a5
Create Date: 2026-11-11 01:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "c8d9e0f1a2b3"
down_revision = "b7c1d2e3f4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    table = sa.table("CONFIG_MEDIA", sa.column("ANIME_LAYOUT", sa.String))
    column = table.c.ANIME_LAYOUT
    bind.execute(
        table.update()
        .where(sa.or_(column.is_(None), sa.func.lower(sa.func.trim(column)) == "flat"))
        .values(ANIME_LAYOUT="category")
    )


def downgrade() -> None:
    """不回滚：改回 flat 会让作品重新落到库根，属于回归缺陷."""
    return
