"""consolidate metadata backfill

Revision ID: 0d5187136482
Revises: 84ccf56c0f47
Create Date: 2026-10-24 14:15:00.000000

统一在 Alembic 内完成订阅锚点、身份和图片来源迁移。
旧脚本不再参与启动或发布流程。
"""

from __future__ import annotations

import json
import secrets
import time

import sqlalchemy as sa

from alembic import op

revision = "0d5187136482"
down_revision = "84ccf56c0f47"
branch_labels = None
depends_on = None

_BACKUP = "MIGRATION_METADATA_BACKUP"
_TABLES = ("SUBSCRIBE_MOVIES", "SUBSCRIBE_TVS")
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _new_ulid() -> str:
    value = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    chars = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


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


def _identity(raw: str):
    value = str(raw or "").strip()
    upper = value.upper()
    if upper.startswith("DB:") and value[3:]:
        return "douban", value[3:], "default", "douban_primary"
    if upper.startswith("BG:") and value[3:]:
        return "bangumi", value[3:], "anime", "bangumi_primary"
    if value.isdigit():
        return "tmdb", value, "default", "tmdb_primary"
    return None


def _backup_table(connection) -> sa.Table:
    inspector = sa.inspect(connection)
    if _BACKUP not in inspector.get_table_names():
        op.create_table(
            _BACKUP,
            sa.Column("ID", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("KIND", sa.String(32), nullable=False),
            sa.Column("TABLE_NAME", sa.String(64), nullable=True),
            sa.Column("ROW_ID", sa.Integer, nullable=True),
            sa.Column("PAYLOAD", sa.Text, nullable=False),
        )
    return sa.Table(_BACKUP, sa.MetaData(), autoload_with=connection)


def upgrade() -> None:
    connection = op.get_bind()
    backup = _backup_table(connection)
    inspector = sa.inspect(connection)
    required = {"MEDIA_IDENTITY", "MEDIA_EXTERNAL_REF"}
    if not required.issubset(set(inspector.get_table_names())):
        return
    identities = sa.Table("MEDIA_IDENTITY", sa.MetaData(), autoload_with=connection)
    refs = sa.Table("MEDIA_EXTERNAL_REF", sa.MetaData(), autoload_with=connection)
    now = sa.func.now()
    for table_name in _TABLES:
        if table_name not in inspector.get_table_names():
            continue
        table = sa.Table(table_name, sa.MetaData(), autoload_with=connection)
        rows = connection.execute(sa.select(table)).mappings().all()
        for row in rows:
            provider = str(row["ANCHOR_PROVIDER"] or "").strip()
            external = str(row["ANCHOR_EXTERNAL_ID"] or "").strip()
            parsed = _identity(row["TMDBID"])
            if not provider or not external:
                if parsed is None:
                    continue
                provider, external, profile, policy = parsed
            else:
                profile = str(row["CONTENT_PROFILE"] or "default")
                policy = str(row["METADATA_POLICY"] or "")
                if not policy:
                    policy = {
                        "douban": "douban_primary",
                        "bangumi": "bangumi_primary",
                        "tmdb": "tmdb_primary",
                    }.get(provider, "")
            scope = "default"
            existing = connection.execute(
                sa.select(refs.c.IDENTITY_ID).where(
                    refs.c.PROVIDER == provider,
                    refs.c.EXTERNAL_ID == external,
                    refs.c.SCOPE == scope,
                )
            ).first()
            created_identity = False
            if existing:
                identity_id = existing[0]
            else:
                identity_id = _new_ulid()
                created_identity = True
                connection.execute(
                    identities.insert().values(
                        IDENTITY_ID=identity_id,
                        MEDIA_TYPE="movie" if table_name == "SUBSCRIBE_MOVIES" else "tv",
                        CONTENT_PROFILE=profile,
                        CANONICAL_TITLE=row["NAME"],
                        YEAR=row["YEAR"],
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
                        MEDIA_TYPE="movie" if table_name == "SUBSCRIBE_MOVIES" else "tv",
                        SCOPE=scope,
                        CONFIDENCE=1.0,
                        LINK_METHOD="legacy_migration_v2",
                        LINK_CONFIDENCE=1.0,
                        REVIEWED=1,
                        IS_PRIMARY=1,
                        CREATED_AT=now,
                        UPDATED_AT=now,
                    )
                )
            target = {
                "ANCHOR_PROVIDER": provider,
                "ANCHOR_EXTERNAL_ID": external,
                "CONTENT_PROFILE": profile,
                "METADATA_POLICY": policy or None,
                "IDENTITY_ID": identity_id,
            }
            changed = any(str(row[key] or "") != str(target[key] or "") for key in target)
            if not changed:
                continue
            connection.execute(
                backup.insert().values(
                    KIND="subscription",
                    TABLE_NAME=table_name,
                    ROW_ID=row["ID"],
                    PAYLOAD=json.dumps(
                        {
                            "ANCHOR_PROVIDER": row["ANCHOR_PROVIDER"],
                            "ANCHOR_EXTERNAL_ID": row["ANCHOR_EXTERNAL_ID"],
                            "CONTENT_PROFILE": row["CONTENT_PROFILE"],
                            "METADATA_POLICY": row["METADATA_POLICY"],
                            "IDENTITY_ID": row["IDENTITY_ID"],
                            "CREATED_IDENTITY": created_identity,
                            "PROVIDER": provider,
                            "EXTERNAL_ID": external,
                            "SCOPE": scope,
                        }
                    ),
                )
            )
            connection.execute(table.update().where(table.c.ID == row["ID"]).values(**target))


def downgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if _BACKUP not in inspector.get_table_names():
        return
    backup = sa.Table(_BACKUP, sa.MetaData(), autoload_with=connection)
    rows = connection.execute(sa.select(backup).order_by(backup.c.ID.desc())).mappings().all()
    for row in rows:
        payload = json.loads(row["PAYLOAD"] or "{}")
        if row["KIND"] == "subscription" and row["TABLE_NAME"] in _TABLES:
            table = sa.Table(row["TABLE_NAME"], sa.MetaData(), autoload_with=connection)
            connection.execute(
                table.update()
                .where(table.c.ID == row["ROW_ID"])
                .values(
                    ANCHOR_PROVIDER=payload.get("ANCHOR_PROVIDER"),
                    ANCHOR_EXTERNAL_ID=payload.get("ANCHOR_EXTERNAL_ID"),
                    CONTENT_PROFILE=payload.get("CONTENT_PROFILE"),
                    METADATA_POLICY=payload.get("METADATA_POLICY"),
                    IDENTITY_ID=payload.get("IDENTITY_ID"),
                )
            )
    # 删除本次迁移创建的 identity/ref，只删除仍没有其他引用的 identity。
    if "MEDIA_EXTERNAL_REF" in inspector.get_table_names() and "MEDIA_IDENTITY" in inspector.get_table_names():
        refs = sa.Table("MEDIA_EXTERNAL_REF", sa.MetaData(), autoload_with=connection)
        identities = sa.Table("MEDIA_IDENTITY", sa.MetaData(), autoload_with=connection)
        created = [
            json.loads(item["PAYLOAD"] or "{}")
            for item in rows
            if item["KIND"] == "subscription" and json.loads(item["PAYLOAD"] or "{}").get("CREATED_IDENTITY")
        ]
        for item in created:
            connection.execute(
                refs.delete().where(
                    refs.c.IDENTITY_ID == item.get("IDENTITY_ID"),
                    refs.c.PROVIDER == item.get("PROVIDER"),
                    refs.c.EXTERNAL_ID == item.get("EXTERNAL_ID"),
                    refs.c.SCOPE == item.get("SCOPE"),
                    refs.c.LINK_METHOD == "legacy_migration_v2",
                )
            )
        for item in created:
            identity_id = item.get("IDENTITY_ID")
            if not identity_id:
                continue
            remaining = connection.execute(
                sa.select(sa.func.count()).select_from(refs).where(refs.c.IDENTITY_ID == identity_id)
            ).scalar()
            if not remaining:
                connection.execute(identities.delete().where(identities.c.IDENTITY_ID == identity_id))
    op.drop_table(_BACKUP)
