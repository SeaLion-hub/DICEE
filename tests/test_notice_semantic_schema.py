"""시맨틱 검색 요청 스키마 검증."""

import pytest
from app.schemas.notice_semantic import NoticeSemanticSearchRequest
from pydantic import ValidationError


def test_notice_semantic_search_request_rejects_inverted_date_range() -> None:
    with pytest.raises(ValidationError, match="published_to"):
        NoticeSemanticSearchRequest(
            college_external_id="c1",
            published_from="2026-03-01T00:00:00+00:00",
            published_to="2026-01-01T00:00:00+00:00",
            query="scholarship",
        )
