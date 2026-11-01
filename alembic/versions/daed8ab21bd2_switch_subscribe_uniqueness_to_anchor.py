"""switch subscribe uniqueness to anchor

Revision ID: daed8ab21bd2
Revises: 9dd288f9bf97
Create Date: 2026-10-24 16:10:00.000000
"""

from __future__ import annotations

import json

import sqlalchemy as sa

from alembic import op

revision = "daed8ab21bd2"
down_revision = "9dd288f9bf97"
branch_labels = None
depends_on = None

_BACKUP = "MIGRATION_SUBSCRIBE_DEDUP"
_OLD_INDEXES = (
    ("SUBSCRIBE_MOVIES", "UQ_SUBSCRIBE_MOVIES_USER_TMDB", ["USER_ID", "TMDBID"]),
    ("SUBSCRIBE_TVS", "UQ_SUBSCRIBE_TVS_USER_TMDB_SEASON", ["USER_ID", "TMDBID", "SEASON"]),
)
_NEW_INDEXES = (
    (
        "SUBSCRIBE_MOVIES",
        "UQ_SUBSCRIBE_MOVIES_USER_ANCHOR",
        ["USER_ID", "ANCHOR_PROVIDER", "ANCHOR_EXTERNAL_ID"],
    ),
    (
        "SUBSCRIBE_TVS",
        "UQ_SUBSCRIBE_TVS_USER_ANCHOR_SEASON",
        ["USER_ID", "ANCHOR_PROVIDER", "ANCHOR_EXTERNAL_ID", "SEASON"],
    ),
)


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _index_names(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {str(index["name"]) for index in _inspector().get_indexes(table) if index.get("name")}


def _drop_index(table: str, name: str) -> None:
    if name in _index_names(table):
        op.drop_index(name, table_name=table)


def _create_index(table: str, name: str, columns: list[str], *, unique: bool = True) -> None:
    if name in _index_names(table):
        return
    op.create_index(name, table, columns, unique=unique)


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


def _dedupe(connection, table_name: str, key_columns: list[str], backup: sa.Table) -> None:
    if not _has_table(table_name):
        return
    table = sa.Table(table_name, sa.MetaData(), autoload_with=connection)
    columns = [table.c[name] for name in key_columns]
    groups = (
        connection.execute(
            sa.select(*columns, sa.func.count().label("TOTAL"), sa.func.max(table.c.ID).label("KEEP_ID"))
            .where(table.c.ANCHOR_PROVIDER.is_not(None), table.c.ANCHOR_PROVIDER != "")
            .where(table.c.ANCHOR_EXTERNAL_ID.is_not(None), table.c.ANCHOR_EXTERNAL_ID != "")
            .group_by(*columns)
            .having(sa.func.count() > 1)
        )
        .mappings()
        .all()
    )
    for group in groups:
        keep_id = int(group["KEEP_ID"])
        rows = (
            connection.execute(
                sa.select(table).where(
                    *[table.c[name] == group[name] for name in key_columns],
                    table.c.ID != keep_id,
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            payload = json.dumps(dict(row), ensure_ascii=False, default=str)
            connection.execute(backup.insert().values(TABLE_NAME=table_name, ROW_ID=int(row["ID"]), PAYLOAD=payload))
            connection.execute(table.delete().where(table.c.ID == int(row["ID"])))


def _backfill_episodes(connection) -> None:
    if not (_has_table("SUBSCRIBE_TV_EPISODES") and _has_table("SUBSCRIBE_TVS")):
        return
    subscriptions = sa.Table("SUBSCRIBE_TVS", sa.MetaData(), autoload_with=connection)
    episodes = sa.Table("SUBSCRIBE_TV_EPISODES", sa.MetaData(), autoload_with=connection)
    scope = {
        int(row["ID"]): row
        for row in connection.execute(
            sa.select(
                subscriptions.c.ID,
                subscriptions.c.IDENTITY_ID,
                subscriptions.c.ANCHOR_PROVIDER,
                subscriptions.c.ANCHOR_EXTERNAL_ID,
                subscriptions.c.CONTENT_PROFILE,
            )
        ).mappings()
    }
    for row in connection.execute(sa.select(episodes)).mappings().all():
        try:
            parent = scope.get(int(str(row.get("RSSID") or "")))
        except (TypeError, ValueError):
            parent = None
        if not parent:
            continue
        connection.execute(
            episodes.update()
            .where(episodes.c.ID == row["ID"])
            .values(
                IDENTITY_ID=parent["IDENTITY_ID"],
                ANCHOR_PROVIDER=parent["ANCHOR_PROVIDER"],
                ANCHOR_EXTERNAL_ID=parent["ANCHOR_EXTERNAL_ID"],
                CONTENT_PROFILE=parent["CONTENT_PROFILE"],
            )
        )


def _season_key(value) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("s"):
        text = text[1:]
    return str(int(text)) if text.isdigit() else text


def _backfill_torrents(connection) -> None:
    if not _has_table("SUBSCRIBE_TORRENTS"):
        return
    torrents = sa.Table("SUBSCRIBE_TORRENTS", sa.MetaData(), autoload_with=connection)
    scopes: dict[tuple[str, str, str, str], set[tuple[str | None, str | None, str | None, str | None]]] = {}
    for table_name, media_type in (("SUBSCRIBE_MOVIES", "movie"), ("SUBSCRIBE_TVS", "tv")):
        if not _has_table(table_name):
            continue
        table = sa.Table(table_name, sa.MetaData(), autoload_with=connection)
        season = table.c.SEASON if "SEASON" in table.c else sa.literal("")
        for row in connection.execute(
            sa.select(
                table.c.NAME,
                table.c.YEAR,
                season.label("SEASON"),
                table.c.IDENTITY_ID,
                table.c.ANCHOR_PROVIDER,
                table.c.ANCHOR_EXTERNAL_ID,
                table.c.CONTENT_PROFILE,
            )
        ).mappings():
            key = (
                media_type,
                str(row["NAME"] or ""),
                str(row["YEAR"] or ""),
                _season_key(row["SEASON"]),
            )
            scopes.setdefault(key, set()).add(
                (
                    row["IDENTITY_ID"],
                    row["ANCHOR_PROVIDER"],
                    row["ANCHOR_EXTERNAL_ID"],
                    row["CONTENT_PROFILE"],
                )
            )
    for row in connection.execute(sa.select(torrents)).mappings().all():
        raw_type = str(row.get("TYPE") or "").lower()
        media_type = "tv" if raw_type in {"tv", "anime", "show", "series"} else "movie"
        key = (
            media_type,
            str(row.get("TITLE") or ""),
            str(row.get("YEAR") or ""),
            _season_key(row.get("SEASON")),
        )
        candidates = scopes.get(key) or set()
        anchors = {(item[1], item[2]) for item in candidates if item[1] and item[2]}
        if len(anchors) != 1:
            continue
        identity_id, provider, external, profile = next(iter(candidates))
        connection.execute(
            torrents.update()
            .where(torrents.c.ID == row["ID"])
            .values(
                IDENTITY_ID=identity_id,
                ANCHOR_PROVIDER=provider,
                ANCHOR_EXTERNAL_ID=external,
                CONTENT_PROFILE=profile,
            )
        )


def _duplicate_tmdb_groups(connection, table_name: str, columns: list[str]) -> int:
    if not _has_table(table_name):
        return 0
    table = sa.Table(table_name, sa.MetaData(), autoload_with=connection)
    return int(
        connection.execute(
            sa.select(sa.func.count()).select_from(
                sa.select(*[table.c[name] for name in columns], sa.func.count().label("TOTAL"))
                .group_by(*[table.c[name] for name in columns])
                .having(sa.func.count() > 1)
                .subquery()
            )
        ).scalar()
        or 0
    )


def upgrade() -> None:
    connection = op.get_bind()
    backup = _backup_table(connection)

    _backfill_episodes(connection)
    _backfill_torrents(connection)
    _dedupe(connection, "SUBSCRIBE_MOVIES", ["USER_ID", "ANCHOR_PROVIDER", "ANCHOR_EXTERNAL_ID"], backup)
    _dedupe(
        connection,
        "SUBSCRIBE_TVS",
        ["USER_ID", "ANCHOR_PROVIDER", "ANCHOR_EXTERNAL_ID", "SEASON"],
        backup,
    )

    for table, name, _columns in _OLD_INDEXES:
        _drop_index(table, name)
    for table, name, columns in _NEW_INDEXES:
        _create_index(table, name, columns)


def downgrade() -> None:
    for table, name, _columns in _NEW_INDEXES:
        _drop_index(table, name)

    connection = op.get_bind()
    if _has_table(_BACKUP):
        backup = sa.Table(_BACKUP, sa.MetaData(), autoload_with=connection)
        rows = connection.execute(sa.select(backup).order_by(backup.c.ID)).mappings().all()
        for row in rows:
            table = sa.Table(row["TABLE_NAME"], sa.MetaData(), autoload_with=connection)
            payload = json.loads(row["PAYLOAD"] or "{}")
            connection.execute(table.insert().values(**payload))

    for table, name, columns in _OLD_INDEXES:
        if _duplicate_tmdb_groups(connection, table, columns):
            raise RuntimeError(f"{table} 存在重复 TMDB 订阅，无法恢复旧唯一索引")
        _create_index(table, name, columns)
    if _has_table(_BACKUP):
        op.drop_table(_BACKUP)
