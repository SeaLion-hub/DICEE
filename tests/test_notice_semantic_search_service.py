"""notice_semantic_search_service DTO and session-order contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_semantic_search_embeds_before_db_lookup_on_provider_error() -> None:
    from app.services.gemini_text_embedding import EmbeddingProviderError
    from app.services.notice_semantic_search_service import search_public_notices_semantic

    session = AsyncMock()
    with (
        patch(
            "app.services.notice_semantic_search_service.embed_text_sync",
            side_effect=EmbeddingProviderError("provider down"),
        ),
        patch(
            "app.services.notice_semantic_search_service.college_repository.get_by_external_id",
            new_callable=AsyncMock,
        ) as mock_college,
    ):
        with pytest.raises(EmbeddingProviderError):
            await search_public_notices_semantic(
                session,
                college_external_id="missing",
                published_from=datetime(2026, 1, 1, tzinfo=UTC),
                published_to=datetime(2026, 12, 31, tzinfo=UTC),
                query="hello",
                limit=5,
            )

    mock_college.assert_not_awaited()


@pytest.mark.asyncio
async def test_semantic_search_returns_public_list_dtos() -> None:
    from app.constants.embeddings import EMBEDDING_DIM
    from app.domain.contracts.notice_public_contracts import NoticePublicListItemDTO
    from app.services.notice_semantic_search_service import search_public_notices_semantic

    session = AsyncMock()
    college = MagicMock()
    college.id = __import__("uuid").uuid4()
    notice = MagicMock()
    notice.id = __import__("uuid").uuid4()
    notice.college = MagicMock()
    notice.college.external_id = "eng"
    notice.external_id = "n1"
    notice.title = "Title"
    notice.url = "https://example.com/n1"
    notice.published_at = None

    with (
        patch("app.services.notice_semantic_search_service.embed_text_sync", return_value=[0.0] * EMBEDDING_DIM),
        patch(
            "app.services.notice_semantic_search_service.college_repository.get_by_external_id",
            new_callable=AsyncMock,
            return_value=college,
        ),
        patch(
            "app.services.notice_semantic_search_service.notice_repository.search_notices_by_embedding",
            new_callable=AsyncMock,
            return_value=[notice],
        ),
    ):
        out = await search_public_notices_semantic(
            session,
            college_external_id="eng",
            published_from=datetime(2026, 1, 1, tzinfo=UTC),
            published_to=datetime(2026, 12, 31, tzinfo=UTC),
            query="hello",
            limit=5,
        )

    assert len(out) == 1
    assert isinstance(out[0], NoticePublicListItemDTO)
    assert out[0].college_external_id == "eng"
    assert out[0].external_id == "n1"
