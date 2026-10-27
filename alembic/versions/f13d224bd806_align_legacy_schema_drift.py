"""align legacy schema drift

Revision ID: f13d224bd806
Revises: daed8ab21bd2
Create Date: 2026-10-24 17:05:00.000000
"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "f13d224bd806"
down_revision = "daed8ab21bd2"
branch_labels = None
depends_on = None

_BACKUP = "MIGRATION_LEGACY_SEEDS_BACKUP"

_NOT_NULL_COLUMNS = {
    "BRUSH_EVENT_LOG": [
        "TASK_NAME",
        "TORRENT_NAME",
        "DOWNLOAD_ID",
        "REASON",
        "TORRENT_URL",
        "DOWNLOADER_NAME",
        "SITE_NAME",
        "CREATED_AT",
    ],
    "CONFIG_SITE": ["RSSURL"],
    "DOWNLOAD_HISTORY": ["DESC"],
    "SITE_BRUSH_TASK": [
        "RSS_RULE",
        "REMOVE_RULE",
        "ACTIVE_WEEKDAYS",
        "DOWNLOAD_SWITCH",
        "REMOVE_SWITCH",
        "STOP_SWITCH",
        "DAILY_DELETE_LIMIT",
        "MAX_SEEDING",
        "HR_LIMIT",
    ],
    "SUBSCRIBE_HISTORY": ["DESC"],
    "SUBSCRIBE_TV_EPISODES": ["EPISODES"],
    "SYSTEM_DICT": ["VALUE"],
}

_NULLABLE_COLUMNS = {
    "SUBSCRIBE_MOVIES": [
        "YEAR",
        "KEYWORD",
        "TMDBID",
        "IMAGE",
        "OVER_EDITION",
        "FILTER_ORDER",
        "FILTER_RESTYPE",
        "FILTER_PIX",
        "FILTER_RULE",
        "FILTER_TEAM",
        "FILTER_INCLUDE",
        "FILTER_EXCLUDE",
        "SAVE_PATH",
        "FUZZY_MATCH",
        "STATE",
        "NOTE",
    ],
    "SUBSCRIBE_TVS": [
        "YEAR",
        "KEYWORD",
        "SEASON",
        "TMDBID",
        "IMAGE",
        "OVER_EDITION",
        "FILTER_ORDER",
        "FILTER_RESTYPE",
        "FILTER_PIX",
        "FILTER_RULE",
        "FILTER_TEAM",
        "FILTER_INCLUDE",
        "FILTER_EXCLUDE",
        "SAVE_PATH",
        "FUZZY_MATCH",
        "TOTAL_EP",
        "CURRENT_EP",
        "TOTAL",
        "LACK",
        "STATE",
        "NOTE",
    ],
}

_RENAMED_INDEXES = (
    ("CONFIG_SYNC_PATHS", "idx_CONFIG_SYNC_PATHS_ENABLED", "ix_CONFIG_SYNC_PATHS_ENABLED", ["ENABLED"]),
    ("CUSTOM_WORDS", "idx_CUSTOM_WORDS_GROUP_ID", "ix_CUSTOM_WORDS_GROUP_ID", ["GROUP_ID"]),
    ("DOWNLOADER", "idx_DOWNLOADER_ENABLED", "ix_DOWNLOADER_ENABLED", ["ENABLED"]),
    ("DOWNLOADER", "idx_DOWNLOADER_TYPE", "ix_DOWNLOADER_TYPE", ["TYPE"]),
    (
        "SITE_USER_INFO_STATS",
        "idx_SITE_USER_INFO_STATS_USERNAME",
        "ix_SITE_USER_INFO_STATS_USERNAME",
        ["USERNAME"],
    ),
)
_SEARCH_NEW_INDEX = ("ix_SEARCH_RESULT_INFO_SEEDERS", ["SEEDERS"])
_SEED_COLUMNS = {
    "SEARCH_RESULT_INFO": ["SEEDS_EPISODE", "SEEDS_SEASON", "SEEDS_END_EPISODE"],
    "TRANSFER_HISTORY": ["SEEDS_EPISODE", "SEEDS_SEASON", "SEEDS_END_EPISODE"],
}


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _columns(table: str) -> dict[str, Any]:
    if not _has_table(table):
        return {}
    return {column["name"]: column for column in _inspector().get_columns(table)}


def _index_names(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {str(index["name"]) for index in _inspector().get_indexes(table) if index.get("name")}


def _fill_nulls(table: str, columns: list[str]) -> None:
    existing = _columns(table)
    for name in columns:
        if name not in existing:
            continue
        column_type = existing[name]["type"]
        template = 'UPDATE "{0}" SET "{1}" = {2} WHERE "{1}" IS NULL'
        if isinstance(column_type, (sa.Integer, sa.BigInteger, sa.SmallInteger, sa.Float, sa.Numeric)):
            op.execute(sa.text(template.format(table, name, ":value")).bindparams(value=0))
        elif isinstance(column_type, sa.DateTime):
            op.execute(sa.text(template.format(table, name, "current_timestamp")))
        else:
            op.execute(sa.text(template.format(table, name, ":value")).bindparams(value=""))


def _set_nullable(table: str, columns: list[str], nullable: bool) -> None:
    existing = _columns(table)
    changes = [(name, existing[name]) for name in columns if name in existing]
    if not changes:
        return
    if not nullable:
        _fill_nulls(table, [name for name, _ in changes])
    with op.batch_alter_table(table) as batch:
        for name, column in changes:
            if bool(column["nullable"]) == nullable:
                continue
            batch.alter_column(name, existing_type=column["type"], nullable=nullable)


def _drop_index(table: str, name: str) -> None:
    if name in _index_names(table):
        op.drop_index(name, table_name=table)


def _create_index(table: str, name: str, columns: list[str], *, unique: bool = False) -> None:
    if not _has_table(table) or name in _index_names(table):
        return
    existing = _columns(table)
    if not all(column in existing for column in columns):
        return
    op.create_index(name, table, columns, unique=unique)


def _rename_index(table: str, old_name: str, new_name: str, columns: list[str]) -> None:
    names = _index_names(table)
    if new_name in names:
        return
    if old_name not in names:
        _create_index(table, new_name, columns)
        return
    if op.get_bind().dialect.name == "mysql":
        # 外键可能依赖旧索引，MySQL 用 RENAME 保留依赖关系。
        op.execute(f"ALTER TABLE `{table}` RENAME INDEX `{old_name}` TO `{new_name}`")
        return
    _drop_index(table, old_name)
    _create_index(table, new_name, columns)


def _backup_table(connection) -> sa.Table:
    if not _has_table(_BACKUP):
        op.create_table(
            _BACKUP,
            sa.Column("ID", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("TABLE_NAME", sa.String(64), nullable=False),
            sa.Column("ROW_ID", sa.Integer, nullable=False),
            sa.Column("PAYLOAD", sa.Text, nullable=False),
        )
    return sa.Table(_BACKUP, sa.MetaData(), autoload_with=connection)


def _backup_seed_columns(connection, backup: sa.Table) -> None:
    for table_name, columns in _SEED_COLUMNS.items():
        existing = _columns(table_name)
        present = [name for name in columns if name in existing]
        if not present:
            continue
        table = sa.Table(table_name, sa.MetaData(), autoload_with=connection)
        rows = (
            connection.execute(
                sa.select(table.c.ID, *[table.c[name] for name in present]).where(
                    sa.or_(*[table.c[name].is_not(None) for name in present])
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            payload = json.dumps(
                {"ID": row["ID"], "columns": {name: row[name] for name in present}},
                ensure_ascii=False,
                default=str,
            )
            connection.execute(backup.insert().values(TABLE_NAME=table_name, ROW_ID=int(row["ID"]), PAYLOAD=payload))
        with op.batch_alter_table(table_name) as batch:
            for name in present:
                batch.drop_column(name)


def _restore_seed_columns(connection) -> None:
    if not _has_table(_BACKUP):
        return
    backup = sa.Table(_BACKUP, sa.MetaData(), autoload_with=connection)
    rows = connection.execute(sa.select(backup).order_by(backup.c.ID)).mappings().all()
    for table_name, columns in _SEED_COLUMNS.items():
        existing = _columns(table_name)
        missing = [name for name in columns if name not in existing]
        if missing:
            with op.batch_alter_table(table_name) as batch:
                for name in missing:
                    batch.add_column(sa.Column(name, sa.Integer(), nullable=True))
    for row in rows:
        table = sa.Table(row["TABLE_NAME"], sa.MetaData(), autoload_with=connection)
        payload = json.loads(row["PAYLOAD"] or "{}")
        values = payload.get("columns") or {}
        if values:
            connection.execute(table.update().where(table.c.ID == payload["ID"]).values(**values))
    op.drop_table(_BACKUP)


def upgrade() -> None:
    connection = op.get_bind()
    has_legacy_seeds = any(set(columns) & set(_columns(table)) for table, columns in _SEED_COLUMNS.items())
    if has_legacy_seeds:
        _backup_seed_columns(connection, _backup_table(connection))

    for table, columns in _NOT_NULL_COLUMNS.items():
        _set_nullable(table, columns, nullable=False)
    for table, columns in _NULLABLE_COLUMNS.items():
        _set_nullable(table, columns, nullable=True)

    for table, old_name, new_name, columns in _RENAMED_INDEXES:
        _rename_index(table, old_name, new_name, columns)
    _drop_index("SEARCH_RESULT_INFO", "ix_search_result_created_at")
    _rename_index("SEARCH_RESULT_INFO", "idx_SEARCH_RESULT_INFO_SEEDERS", *_SEARCH_NEW_INDEX)


def downgrade() -> None:
    _drop_index("SEARCH_RESULT_INFO", _SEARCH_NEW_INDEX[0])
    _create_index("SEARCH_RESULT_INFO", "idx_SEARCH_RESULT_INFO_SEEDERS", ["SEEDERS"])
    _create_index("SEARCH_RESULT_INFO", "ix_search_result_created_at", ["CREATED_AT"])

    for table, old_name, new_name, columns in reversed(_RENAMED_INDEXES):
        _rename_index(table, new_name, old_name, columns)

    for table, columns in _NULLABLE_COLUMNS.items():
        _set_nullable(table, columns, nullable=False)
    for table, columns in _NOT_NULL_COLUMNS.items():
        _set_nullable(table, columns, nullable=True)

    _restore_seed_columns(op.get_bind())
