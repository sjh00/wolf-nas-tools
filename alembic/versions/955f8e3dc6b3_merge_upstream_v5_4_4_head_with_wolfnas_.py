"""merge upstream v5.4.4 head with wolfnas local head

Revision ID: 955f8e3dc6b3
Revises: 975ece76f366, b8e53a78e03e
Create Date: 2026-11-01 16:46:45.324385

同步上游 v5.4.4 后出现两个 head：

- 975ece76f366：WolfNas 侧的合并点（合并 ONLY_NEXUS_MEDIA 改名链与上游 v4.20 self-heal）
- b8e53a78e03e：上游 v5 在分叉点 3dcf1ef5f1af 之后新增的迁移链末端

两者自同一分叉点 3dcf1ef5f1af 展开，故需本合并点收口，否则
`alembic upgrade head` 会报 "Multiple head revisions are present"。

本迁移只做拓扑合并，不执行任何 schema 变更——两条链的操作互不重叠
（ONLY_WOLF_NAS 仅存在于本地链，其余上游链操作各有 _has_column/has_table 守卫）。
"""

revision = "955f8e3dc6b3"
down_revision = ("975ece76f366", "b8e53a78e03e")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
