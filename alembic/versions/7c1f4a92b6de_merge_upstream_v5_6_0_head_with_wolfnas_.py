"""merge upstream v5.6.0 head with wolfnas local head

Revision ID: 7c1f4a92b6de
Revises: 955f8e3dc6b3, 25e3fd755afa
Create Date: 2026-11-03 11:20:00.000000

同步上游 v5.6.0 后出现两个 head：
- 955f8e3dc6b3：WolfNas 侧的合并点（v5.4.4 合并收口）
- 25e3fd755afa：上游 v5.6.0 新增的媒体生命周期表迁移

两者自 b8e53a78e03e 之后各自延伸，故需本合并点收口，否则
`alembic upgrade head` 会报 "Multiple head revisions are present"。

本迁移只做拓扑合并，不执行任何 schema 变更——两条链的操作互不重叠
（生命周期表仅存在于上游链）。
"""

revision = "7c1f4a92b6de"
down_revision = ("955f8e3dc6b3", "25e3fd755afa")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
