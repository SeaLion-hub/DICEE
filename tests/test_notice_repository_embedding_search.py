"""search_notices_by_embedding 차원 검증 및 세션 호출 계약."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.constants.embeddings import EMBEDDING_DIM
from app.repositories.notice_repository import search_notices_by_embedding


@pytest.mark.asyncio
async def test_search_notices_by_embedding_wrong_dim_raises() -> None:
    """EMBEDDING_DIM이 아니면 ValueError."""
    mock_session = AsyncMock()
    cid = uuid4()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 2, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match=str(EMBEDDING_DIM)):
        await search_notices_by_embedding(
            mock_session,
            college_id=cid,
            published_from=t0,
            published_to=t1,
            query_embedding=[0.0] * 100,
        )
    mock_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_search_notices_by_embedding_executes_select() -> None:
    """올바른 차원이면 execute가 호출되고 스칼라 결과 리스트를 반환한다."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.unique.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    cid = uuid4()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 2, 1, tzinfo=UTC)
    vec = [0.0] * EMBEDDING_DIM
    out = await search_notices_by_embedding(
        mock_session,
        college_id=cid,
        published_from=t0,
        published_to=t1,
        query_embedding=vec,
        limit=5,
    )
    assert out == []
    mock_session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_notices_by_embedding_empty_published_window_returns_empty() -> None:
    """published_from == published_at 상한 published_to와 같으면 published_at < to 조건으로 행이 없다."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.unique.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    cid = uuid4()
    t = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    vec = [0.0] * EMBEDDING_DIM
    out = await search_notices_by_embedding(
        mock_session,
        college_id=cid,
        published_from=t,
        published_to=t,
        query_embedding=vec,
    )
    assert out == []
    mock_session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_notices_by_embedding_inverted_window_returns_empty() -> None:
    """published_from > published_to 이면 SQL 조건으로 매칭 행이 없다."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.unique.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    cid = uuid4()
    t0 = datetime(2026, 3, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    vec = [0.0] * EMBEDDING_DIM
    out = await search_notices_by_embedding(
        mock_session,
        college_id=cid,
        published_from=t0,
        published_to=t1,
        query_embedding=vec,
    )
    assert out == []
    mock_session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_notices_by_embedding_limit_zero_calls_execute() -> None:
    """limit=0이면 DB가 빈 결과를 반환한다(클라이언트는 빈 리스트)."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.unique.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    cid = uuid4()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 2, 1, tzinfo=UTC)
    vec = [0.0] * EMBEDDING_DIM
    out = await search_notices_by_embedding(
        mock_session,
        college_id=cid,
        published_from=t0,
        published_to=t1,
        query_embedding=vec,
        limit=0,
    )
    assert out == []
    mock_session.execute.assert_awaited_once()
