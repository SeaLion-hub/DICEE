from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from app.repositories import user_repository
from sqlalchemy.dialects import postgresql


def _sql(stmt: object) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False}))


class _ExecuteResult:
    rowcount = 0

    def scalars(self) -> MagicMock:
        scalars = MagicMock()
        scalars.one_or_none.return_value = None
        return scalars

    def one_or_none(self) -> None:
        return None


class _CaptureSession:
    def __init__(self) -> None:
        self.statement = None

    async def execute(self, stmt: object) -> _ExecuteResult:
        self.statement = stmt
        return _ExecuteResult()


@pytest.mark.asyncio
async def test_get_by_id_filters_soft_deleted_users() -> None:
    session = _CaptureSession()

    await user_repository.get_by_id(session, uuid.uuid4())

    assert "users.deleted_at IS NULL" in _sql(session.statement)


@pytest.mark.asyncio
async def test_rotate_refresh_token_version_filters_soft_deleted_users() -> None:
    session = _CaptureSession()

    out = await user_repository.rotate_refresh_token_version(session, uuid.uuid4(), 3)

    assert out is None
    assert "users.deleted_at IS NULL" in _sql(session.statement)


@pytest.mark.asyncio
async def test_increment_refresh_token_version_returns_false_when_user_inactive() -> None:
    session = _CaptureSession()

    updated = await user_repository.increment_refresh_token_version(session, uuid.uuid4())

    assert updated is False
    assert "users.deleted_at IS NULL" in _sql(session.statement)
