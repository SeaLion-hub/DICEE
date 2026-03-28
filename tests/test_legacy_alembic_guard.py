"""legacy_alembic_guard: v7 스키마 감지 단위 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from app.legacy_alembic_guard import v7_base_schema_present
from sqlalchemy import Integer
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import Connection


def test_v7_absent_when_no_colleges_table() -> None:
    conn = MagicMock(spec=Connection)
    mock_insp = MagicMock()
    mock_insp.has_table.return_value = False
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.legacy_alembic_guard.inspect", lambda _c: mock_insp)
        assert v7_base_schema_present(conn) is False


def test_v7_present_when_colleges_id_is_uuid() -> None:
    conn = MagicMock(spec=Connection)
    mock_insp = MagicMock()
    mock_insp.has_table.return_value = True
    mock_insp.get_columns.return_value = [
        {"name": "id", "type": PG_UUID(as_uuid=True)},
        {"name": "name", "type": MagicMock()},
    ]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.legacy_alembic_guard.inspect", lambda _c: mock_insp)
        assert v7_base_schema_present(conn) is True


def test_v7_absent_when_colleges_id_is_integer() -> None:
    conn = MagicMock(spec=Connection)
    mock_insp = MagicMock()
    mock_insp.has_table.return_value = True
    mock_insp.get_columns.return_value = [
        {"name": "id", "type": Integer()},
    ]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.legacy_alembic_guard.inspect", lambda _c: mock_insp)
        assert v7_base_schema_present(conn) is False
