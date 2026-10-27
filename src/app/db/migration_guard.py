"""Alembic DDL 幂等守卫。

应用启动时的 ``init_db()`` 会先执行 ``create_all()``，可能把表/列/索引按当前模型
提前建好；随后补跑的迁移里那些无条件 ``create_table`` / ``add_column`` /
``create_index`` 就会抛 ``DuplicateTable`` / ``DuplicateColumn``。
这里给 ``alembic.op`` 加上“目标已存在则跳过”的语义，使迁移可重复执行。
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

import log
from alembic import op as alembic_op

_INSTALLED_FLAG = "_nexus_idempotent_ddl"


def _inspector(op_module: Any) -> sa.Inspector:
    return sa.inspect(op_module.get_bind())


def _has_table(op_module: Any, name: str) -> bool:
    return name in _inspector(op_module).get_table_names()


def _columns(op_module: Any, table: str) -> set[str]:
    if not _has_table(op_module, table):
        return set()
    return {column["name"] for column in _inspector(op_module).get_columns(table)}


def _indexes(op_module: Any, table: str) -> set[str]:
    if not _has_table(op_module, table):
        return set()
    return {str(index["name"]) for index in _inspector(op_module).get_indexes(table) if index.get("name")}


def _constraint_names(op_module: Any, table: str, kind: str) -> set[str]:
    if not _has_table(op_module, table):
        return set()
    inspector = _inspector(op_module)
    items = inspector.get_unique_constraints(table) if kind == "unique" else inspector.get_foreign_keys(table)
    return {str(item.get("name")) for item in items if item.get("name")}


def install_idempotent_ddl(op_module: Any | None = None) -> bool:
    """给 alembic.op 装上幂等守卫，返回是否本次安装成功。"""
    target: Any = op_module or alembic_op
    if getattr(target, _INSTALLED_FLAG, False):
        return False

    original_create_table = target.create_table
    original_add_column = target.add_column
    original_create_index = target.create_index
    original_create_unique = target.create_unique_constraint
    original_create_foreign_key = target.create_foreign_key

    def create_table(*args: Any, **kwargs: Any) -> Any:
        name = args[0] if args else kwargs.get("table_name")
        if name and _has_table(target, str(name)):
            log.info(f"[alembic]表 {name} 已存在，跳过 create_table")
            return None
        return original_create_table(*args, **kwargs)

    def add_column(table_name: str, column: sa.Column, *args: Any, **kwargs: Any) -> Any:
        if column.name in _columns(target, table_name):
            log.info(f"[alembic]{table_name}.{column.name} 已存在，跳过 add_column")
            return None
        return original_add_column(table_name, column, *args, **kwargs)

    def create_index(index_name: str, table_name: str, columns: Any, *args: Any, **kwargs: Any) -> Any:
        if index_name in _indexes(target, table_name):
            log.info(f"[alembic]索引 {index_name} 已存在，跳过 create_index")
            return None
        return original_create_index(index_name, table_name, columns, *args, **kwargs)

    def create_unique_constraint(constraint_name: str, table_name: str, columns: Any, *args: Any, **kwargs: Any) -> Any:
        if constraint_name in _constraint_names(target, table_name, "unique"):
            log.info(f"[alembic]唯一约束 {constraint_name} 已存在，跳过 create_unique_constraint")
            return None
        return original_create_unique(constraint_name, table_name, columns, *args, **kwargs)

    def create_foreign_key(
        constraint_name: str, source_table: str, referent_table: str, *args: Any, **kwargs: Any
    ) -> Any:
        if constraint_name in _constraint_names(target, source_table, "foreign"):
            log.info(f"[alembic]外键 {constraint_name} 已存在，跳过 create_foreign_key")
            return None
        return original_create_foreign_key(constraint_name, source_table, referent_table, *args, **kwargs)

    setattr(target, "create_table", create_table)
    setattr(target, "add_column", add_column)
    setattr(target, "create_index", create_index)
    setattr(target, "create_unique_constraint", create_unique_constraint)
    setattr(target, "create_foreign_key", create_foreign_key)
    setattr(target, _INSTALLED_FLAG, True)
    return True
