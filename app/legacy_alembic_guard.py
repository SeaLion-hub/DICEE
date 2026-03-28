"""v7 초기 스키마 감지: Alembic 빈 DB 시 v7 체인 후 레거시 001→006이 다시 DDL을 실행하지 않도록."""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import Connection


def v7_base_schema_present(conn: Connection) -> bool:
    """colleges.id가 UUID이면 v7_001(또는 동등) 스키마로 간주."""
    insp = inspect(conn)
    if not insp.has_table("colleges"):
        return False
    id_col = next((c for c in insp.get_columns("colleges") if c["name"] == "id"), None)
    if id_col is None:
        return False
    return isinstance(id_col["type"], PG_UUID)
