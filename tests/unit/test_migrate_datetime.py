from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table

from app.db.migrate import _coerce_row_for_table
from app.schemas.auth import UserContext


def test_coerce_iso_datetime_string():
    metadata = MetaData()
    table = Table(
        "RBAC_ROLES",
        metadata,
        Column("ID", Integer),
        Column("ROLE_NAME", String(64)),
        Column("CREATED_AT", DateTime),
        Column("UPDATED_AT", DateTime),
    )
    row = _coerce_row_for_table(
        table,
        {
            "ID": 1,
            "ROLE_NAME": "超级管理员",
            "CREATED_AT": "2026-09-14 04:17:05.579240",
            "UPDATED_AT": "2026-09-14T04:17:05.579240",
        },
    )
    assert isinstance(row["CREATED_AT"], datetime)
    assert isinstance(row["UPDATED_AT"], datetime)
    assert row["ROLE_NAME"] == "超级管理员"


def test_superadmin_has_permission_without_codes():
    user = UserContext(
        user_id=1,
        username="admin",
        level=0,
        permissions=[],
        role_codes=["superadmin"],
    )
    assert user.is_superadmin
    assert user.has_permission("subscription:view")
