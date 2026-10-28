"""add metadata scope columns

Revision ID: 9dd288f9bf97
Revises: 0d5187136482
Create Date: 2026-10-24 14:18:23.550434
"""

from __future__ import annotations

import json
import secrets
import time

import sqlalchemy as sa

from alembic import op

revision = "9dd288f9bf97"
down_revision = "0d5187136482"
branch_labels = None
depends_on = None

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_SCOPE_COLUMNS = (
    ("IDENTITY_ID", sa.String(26)),
    ("ANCHOR_PROVIDER", sa.String(64)),
    ("ANCHOR_EXTERNAL_ID", sa.String(255)),
    ("CONTENT_PROFILE", sa.String(64)),
    ("METADATA_POLICY", sa.String(64)),
    ("NAMING_PROFILE", sa.String(64)),
)
_CHILD_COLUMNS = _SCOPE_COLUMNS[:4]
_TABLE_COLUMNS = {
    "SEARCH_RESULT_INFO": _SCOPE_COLUMNS,
    "LIBRARY_MEDIA_METADATA": _SCOPE_COLUMNS,
    "SUBSCRIBE_HISTORY": _SCOPE_COLUMNS,
    "SUBSCRIBE_TORRENTS": _CHILD_COLUMNS,
    "SUBSCRIBE_TV_EPISODES": _CHILD_COLUMNS,
    "MEDIASYNC_ITEMS": _CHILD_COLUMNS,
}
_IDENTITY_INDEXES = {
    "SEARCH_RESULT_INFO": "ix_SEARCH_RESULT_INFO_IDENTITY_ID",
    "LIBRARY_MEDIA_METADATA": "ix_LIBRARY_MEDIA_METADATA_IDENTITY_ID",
    "MEDIASYNC_ITEMS": "ix_MEDIASYNC_ITEMS_IDENTITY_ID",
}
_BACKFILL = (
    ("SUBSCRIBE_HISTORY", "TYPE", "TMDBID", "NAME", "YEAR", True),
    ("SEARCH_RESULT_INFO", "TYPE", "TMDBID", "TITLE", "YEAR", True),
    ("LIBRARY_MEDIA_METADATA", "TYPE", "TMDBID", "TITLE", "YEAR", True),
    ("MEDIASYNC_ITEMS", "ITEM_TYPE", "TMDBID", "TITLE", "YEAR", False),
    ("DOWNLOAD_HISTORY", "TYPE", "TMDBID", "TITLE", "YEAR", False),
    ("TRANSFER_HISTORY", "TYPE", "TMDBID", "TITLE", "YEAR", False),
)


def _new_ulid() -> str:
    value = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    chars = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _columns(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {column["name"] for column in _inspector().get_columns(table)}


def _index_names(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {str(index["name"]) for index in _inspector().get_indexes(table) if index.get("name")}


def _add_columns(table: str, columns) -> None:
    if not _has_table(table):
        return
    existing = _columns(table)
    for name, column_type in columns:
        if name not in existing:
            op.add_column(table, sa.Column(name, column_type, nullable=True))


def _drop_columns(table: str, columns) -> None:
    if not _has_table(table):
        return
    existing = _columns(table)
    for name, _ in reversed(columns):
        if name in existing:
            with op.batch_alter_table(table) as batch_op:
                batch_op.drop_column(name)


def _drop_index(table: str, name: str) -> None:
    if name in _index_names(table):
        op.drop_index(name, table_name=table)


def _create_index(table: str, name: str, columns, unique: bool = False) -> None:
    if name in _index_names(table):
        return
    if not set(columns).issubset(_columns(table)):
        return
    op.create_index(name, table, columns, unique=unique)


def _parse_ref(raw, media_type: str):
    value = str(raw or "").strip()
    upper = value.upper()
    if upper.startswith("DB:") and value[3:]:
        return "douban", value[3:], "default", "douban_primary"
    if upper.startswith("BG:") and value[3:]:
        return "bangumi", value[3:], "anime", "bangumi_primary"
    if value.isdigit():
        return "tmdb", value, "anime" if media_type == "anime" else "default", "tmdb_primary"
    if value.lower().startswith("tt") and value[2:].isdigit():
        return "imdb", value.lower(), "default", None
    return None


def _policy_for(provider: str) -> str:
    return {
        "tmdb": "tmdb_primary",
        "douban": "douban_primary",
        "bangumi": "bangumi_primary",
    }.get(provider, "")


def _media_type(row, type_key: str) -> str:
    value = str(row.get(type_key) or "").strip().lower()
    if value in {"tv", "show", "series", "episode", "season", "电视剧", "剧集"}:
        return "tv"
    return "movie"


def _ref_id_value(connection, refs: sa.Table) -> dict:
    """仅在主键没有数据库默认/自增时才手工补 ID.

    PostgreSQL 的 Sequence、MySQL 的 AUTO_INCREMENT、SQLite 的 INTEGER PRIMARY KEY
    都会自行生成主键；显式 max+1 会绕过序列，导致后续 ORM 插入冲突。
    """
    column = refs.c.ID
    if column.server_default is not None or column.autoincrement in (True, "auto"):
        return {}
    current = connection.execute(sa.select(sa.func.coalesce(sa.func.max(column), 0))).scalar()
    return {"ID": int(current or 0) + 1}


def _ensure_identity(
    connection,
    identities: sa.Table,
    refs: sa.Table,
    *,
    provider: str,
    external: str,
    media_type: str,
    profile: str,
    title,
    year,
) -> str:
    scope = "default"
    existing = connection.execute(
        sa.select(refs.c.IDENTITY_ID).where(
            refs.c.PROVIDER == provider,
            refs.c.EXTERNAL_ID == external,
            refs.c.SCOPE == scope,
        )
    ).first()
    if existing:
        return str(existing[0])

    identity_id = _new_ulid()
    now = sa.func.now()
    connection.execute(
        identities.insert().values(
            IDENTITY_ID=identity_id,
            MEDIA_TYPE=media_type,
            CONTENT_PROFILE=profile,
            CANONICAL_TITLE=str(title or "")[:255] or None,
            YEAR=str(year or "")[:8] or None,
            CREATED_AT=now,
            UPDATED_AT=now,
        )
    )
    connection.execute(
        refs.insert().values(
            **_ref_id_value(connection, refs),
            IDENTITY_ID=identity_id,
            PROVIDER=provider,
            EXTERNAL_ID=external,
            MEDIA_TYPE=media_type,
            SCOPE=scope,
            CONFIDENCE=1.0,
            LINK_METHOD="legacy_migration_scope",
            LINK_CONFIDENCE=1.0,
            REVIEWED=1,
            IS_PRIMARY=1,
            CREATED_AT=now,
            UPDATED_AT=now,
        )
    )
    return identity_id


def _library_ref(row) -> tuple[str, str]:
    try:
        raw = json.loads(row.get("RAW") or "{}")
    except (TypeError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    provider = str(raw.get("anchor_provider") or "").strip()
    external = str(raw.get("anchor_external_id") or "").strip()
    raw_id = str(row.get("TMDBID") or raw.get("tmdbid") or "").strip()
    if provider and external:
        return provider, external
    return "", raw_id


def _backfill_subscriptions(connection, identities: sa.Table, refs: sa.Table) -> None:
    for table_name, media_type in (("SUBSCRIBE_MOVIES", "movie"), ("SUBSCRIBE_TVS", "tv")):
        if not _has_table(table_name):
            continue
        available = _columns(table_name)
        table = sa.Table(table_name, sa.MetaData(), autoload_with=connection)
        for row in connection.execute(sa.select(table)).mappings().all():
            provider = str(row.get("ANCHOR_PROVIDER") or "").strip()
            external = str(row.get("ANCHOR_EXTERNAL_ID") or "").strip()
            profile = str(row.get("CONTENT_PROFILE") or "").strip()
            policy = str(row.get("METADATA_POLICY") or "").strip()
            if not provider or not external:
                parsed = _parse_ref(row.get("TMDBID"), media_type)
                if parsed is None:
                    continue
                provider, external, parsed_profile, parsed_policy = parsed
                profile = profile or parsed_profile
                policy = policy or (parsed_policy or "")
            if not provider or not external:
                continue
            profile = profile or "default"
            policy = policy or _policy_for(provider)
            identity_id = _ensure_identity(
                connection,
                identities,
                refs,
                provider=provider,
                external=external,
                media_type=media_type,
                profile=profile,
                title=row.get("NAME"),
                year=row.get("YEAR"),
            )
            target: dict[str, str | None] = {
                "ANCHOR_PROVIDER": provider,
                "ANCHOR_EXTERNAL_ID": external,
                "IDENTITY_ID": identity_id,
                "CONTENT_PROFILE": profile,
                "METADATA_POLICY": policy or None,
            }
            changed = {
                key: value
                for key, value in target.items()
                if key in available and str(row.get(key) or "") != str(value or "")
            }
            if changed:
                connection.execute(table.update().where(table.c.ID == row["ID"]).values(**changed))


def _backfill_table(connection, identities: sa.Table, refs: sa.Table, spec) -> None:
    table_name, type_key, raw_key, title_key, year_key, has_policy = spec
    if not _has_table(table_name):
        return
    available = _columns(table_name)
    if not {"ANCHOR_PROVIDER", "ANCHOR_EXTERNAL_ID", "IDENTITY_ID", "CONTENT_PROFILE"}.issubset(available):
        return
    table = sa.Table(table_name, sa.MetaData(), autoload_with=connection)
    for row in connection.execute(sa.select(table)).mappings().all():
        provider = str(row.get("ANCHOR_PROVIDER") or "").strip()
        external = str(row.get("ANCHOR_EXTERNAL_ID") or "").strip()
        raw = row.get(raw_key)
        if table_name == "LIBRARY_MEDIA_METADATA":
            provider, external = _library_ref(row)
        elif table_name == "MEDIASYNC_ITEMS" and (not external or not provider):
            if not str(raw or "").strip():
                raw = row.get("IMDBID")
        media_type = _media_type(row, type_key)
        profile = str(row.get("CONTENT_PROFILE") or "").strip()

        policy = str(row.get("METADATA_POLICY") or "").strip() if has_policy else ""
        if not provider or not external:
            parsed = _parse_ref(raw, media_type)
            if parsed is None:
                continue
            provider, external, parsed_profile, parsed_policy = parsed
            profile = profile or parsed_profile
            policy = policy or (parsed_policy or "")
        if not provider or not external:
            continue
        profile = profile or "default"
        policy = policy or _policy_for(provider)

        identity_id = _ensure_identity(
            connection,
            identities,
            refs,
            provider=provider,
            external=external,
            media_type=media_type,
            profile=profile,
            title=row.get(title_key),
            year=row.get(year_key),
        )
        target: dict[str, str | None] = {
            "ANCHOR_PROVIDER": provider,
            "ANCHOR_EXTERNAL_ID": external,
            "IDENTITY_ID": identity_id,
            "CONTENT_PROFILE": profile,
        }
        if has_policy:
            target["METADATA_POLICY"] = policy or None
        changed = {
            key: value
            for key, value in target.items()
            if key in available and str(row.get(key) or "") != str(value or "")
        }
        if changed:
            connection.execute(table.update().where(table.c.ID == row["ID"]).values(**changed))


def upgrade() -> None:
    for table, columns in _TABLE_COLUMNS.items():
        _add_columns(table, columns)
    for table, index_name in _IDENTITY_INDEXES.items():
        _create_index(table, index_name, ["IDENTITY_ID"])

    connection = op.get_bind()
    if {"MEDIA_IDENTITY", "MEDIA_EXTERNAL_REF"}.issubset(set(_inspector().get_table_names())):
        identities = sa.Table("MEDIA_IDENTITY", sa.MetaData(), autoload_with=connection)
        refs = sa.Table("MEDIA_EXTERNAL_REF", sa.MetaData(), autoload_with=connection)
        _backfill_subscriptions(connection, identities, refs)
        for spec in _BACKFILL:
            _backfill_table(connection, identities, refs, spec)


def downgrade() -> None:
    connection = op.get_bind()
    if {"MEDIA_IDENTITY", "MEDIA_EXTERNAL_REF"}.issubset(set(_inspector().get_table_names())):
        refs = sa.Table("MEDIA_EXTERNAL_REF", sa.MetaData(), autoload_with=connection)
        identities = sa.Table("MEDIA_IDENTITY", sa.MetaData(), autoload_with=connection)
        identity_ids = [
            row[0]
            for row in connection.execute(
                sa.select(refs.c.IDENTITY_ID).where(refs.c.LINK_METHOD == "legacy_migration_scope").distinct()
            ).all()
        ]
        connection.execute(refs.delete().where(refs.c.LINK_METHOD == "legacy_migration_scope"))
        for identity_id in identity_ids:
            remaining = connection.execute(
                sa.select(sa.func.count()).select_from(refs).where(refs.c.IDENTITY_ID == identity_id)
            ).scalar()
            if not remaining:
                connection.execute(identities.delete().where(identities.c.IDENTITY_ID == identity_id))

    for table, index_name in _IDENTITY_INDEXES.items():
        _drop_index(table, index_name)
    for table, columns in _TABLE_COLUMNS.items():
        _drop_columns(table, columns)
