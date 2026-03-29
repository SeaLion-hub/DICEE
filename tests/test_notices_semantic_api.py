"""POST /v1/notices/search/semantic 라우터 동작 (서비스는 mock)."""

from unittest.mock import AsyncMock, patch

import pytest
from app.core.exceptions import EmptySemanticQueryError
from app.services.notice_public_service import UnknownCollegeExternalIdError
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    ("side_effect", "expected_status"),
    [
        (UnknownCollegeExternalIdError("x"), 404),
        (EmptySemanticQueryError(), 400),
    ],
)
def test_semantic_search_maps_service_errors(
    client: TestClient,
    side_effect: Exception,
    expected_status: int,
) -> None:
    with patch(
        "app.api.v1.notices.search_public_notices_semantic",
        new_callable=AsyncMock,
        side_effect=side_effect,
    ):
        r = client.post(
            "/v1/notices/search/semantic",
            json={
                "college_external_id": "test-college",
                "published_from": "2026-01-01T00:00:00Z",
                "published_to": "2026-12-31T00:00:00Z",
                "query": "hello",
                "limit": 5,
            },
        )
    assert r.status_code == expected_status
    if expected_status == 400:
        assert r.json().get("detail") == "query must be non-empty"


def test_semantic_search_valueerror_from_service_returns_500_without_leaking_message(
    client: TestClient,
) -> None:
    """서비스가 ValueError를 올리면 500은 마스킹되고 임의 메시지는 body에 없어야 한다."""
    with (
        patch(
            "app.api.v1.notices.search_public_notices_semantic",
            new_callable=AsyncMock,
            side_effect=ValueError("internal-embedding-dim-leak-xyz"),
        ),
        TestClient(client.app, raise_server_exceptions=False) as c,
    ):
        r = c.post(
            "/v1/notices/search/semantic",
            json={
                "college_external_id": "test-college",
                "published_from": "2026-01-01T00:00:00Z",
                "published_to": "2026-12-31T00:00:00Z",
                "query": "hello",
                "limit": 5,
            },
        )
    assert r.status_code == 500
    body = r.text
    assert "internal-embedding-dim-leak-xyz" not in body
    assert r.json().get("detail") == "Internal server error"


def test_semantic_search_returns_items_when_service_returns_notices(client: TestClient) -> None:
    from app.models.college import College
    from app.models.notice import Notice

    college = College(name="C", external_id="cext")
    college.id = __import__("uuid").uuid4()
    n = Notice(
        college_id=college.id,
        external_id="e1",
        title="T",
        url="https://example.com/n",
        published_at=None,
    )
    n.id = __import__("uuid").uuid4()
    n.college = college

    async def _fake(*_a: object, **_kw: object):
        return [n]

    with patch(
        "app.api.v1.notices.search_public_notices_semantic",
        new_callable=AsyncMock,
        side_effect=_fake,
    ):
        r = client.post(
            "/v1/notices/search/semantic",
            json={
                "college_external_id": "cext",
                "published_from": "2026-01-01T00:00:00Z",
                "published_to": "2026-12-31T00:00:00Z",
                "query": "hello",
                "limit": 5,
            },
        )
    assert r.status_code == 200
    data = r.json()
    assert data["limit"] == 5
    assert len(data["items"]) == 1
    assert data["items"][0]["external_id"] == "e1"
