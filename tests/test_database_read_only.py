"""읽기 전용 세션 래퍼 및 get_read_only_db 방어 동작 검증."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.database import (
    READ_ONLY_SESSION_MSG,
    ReadOnlySessionWrapper,
)


@pytest.fixture
def mock_async_session():
    s = MagicMock()
    s.commit = AsyncMock()
    s.flush = AsyncMock()
    s.execute = AsyncMock(return_value=None)
    return s


@pytest.mark.asyncio
async def test_read_only_session_wrapper_commit_raises(mock_async_session):
    wrapper = ReadOnlySessionWrapper(mock_async_session)
    with pytest.raises(RuntimeError, match=READ_ONLY_SESSION_MSG):
        await wrapper.commit()
    mock_async_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_read_only_session_wrapper_flush_raises(mock_async_session):
    wrapper = ReadOnlySessionWrapper(mock_async_session)
    with pytest.raises(RuntimeError, match=READ_ONLY_SESSION_MSG):
        await wrapper.flush()
    mock_async_session.flush.assert_not_called()


@pytest.mark.asyncio
async def test_read_only_session_wrapper_delegates_execute(mock_async_session):
    wrapper = ReadOnlySessionWrapper(mock_async_session)
    await wrapper.execute("SELECT 1")
    mock_async_session.execute.assert_called_once_with("SELECT 1")
