"""공개 공지 API 스켈레톤. DB 없이 서비스 레이어 패치로 라우터·상태 코드 검증."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from app.domain.contracts.notice_public_contracts import NoticePublicDetailDTO, NoticePublicListItemDTO
from app.services.notice_public_service import UnknownCollegeExternalIdError
from sqlalchemy.exc import OperationalError


@pytest.mark.asyncio
async def test_list_notices_returns_200_empty(async_client: httpx.AsyncClient) -> None:
    with patch("app.api.v1.notices.list_public_notices", new_callable=AsyncMock) as m:
        m.return_value = ([], None)
        resp = await async_client.get("/v1/notices")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["next_cursor"] is None
        assert data["limit"] == 20


@pytest.mark.asyncio
async def test_list_notices_unknown_college_returns_404(async_client: httpx.AsyncClient) -> None:
    with patch("app.api.v1.notices.list_public_notices", new_callable=AsyncMock) as m:
        m.side_effect = UnknownCollegeExternalIdError("no-such-college")
        resp = await async_client.get("/v1/notices", params={"college_external_id": "no-such-college"})
        assert resp.status_code == 404
        assert "College" in resp.json().get("detail", "")


@pytest.mark.asyncio
async def test_list_notices_respects_limit_query(async_client: httpx.AsyncClient) -> None:
    nid = uuid.uuid4()
    item = NoticePublicListItemDTO(
        id=nid,
        college_external_id="eng",
        external_id="1",
        title="t",
        url=None,
        published_at=None,
    )
    with patch("app.api.v1.notices.list_public_notices", new_callable=AsyncMock) as m:
        m.return_value = ([item], "next-page-cursor")
        resp = await async_client.get("/v1/notices", params={"limit": 5})
        assert resp.status_code == 200
        body = resp.json()
        assert body["limit"] == 5
        assert len(body["items"]) == 1
        assert body["next_cursor"] == "next-page-cursor"


@pytest.mark.asyncio
async def test_get_notice_not_found_returns_404(async_client: httpx.AsyncClient) -> None:
    nid = uuid.uuid4()
    with patch("app.api.v1.notices.get_public_notice_by_id", new_callable=AsyncMock) as m:
        m.return_value = None
        resp = await async_client.get(f"/v1/notices/{nid}")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_notice_found_returns_200(async_client: httpx.AsyncClient) -> None:
    nid = uuid.uuid4()
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    detail = NoticePublicDetailDTO(
        id=nid,
        college_external_id="eng",
        external_id="1",
        title="Hello",
        url="https://example.com/n/1",
        published_at=now,
        content_url="https://bucket/x",
        created_at=now,
        updated_at=now,
    )
    with patch("app.api.v1.notices.get_public_notice_by_id", new_callable=AsyncMock) as m:
        m.return_value = detail
        resp = await async_client.get(f"/v1/notices/{nid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Hello"
        assert data["content_url"] == "https://bucket/x"


@pytest.mark.asyncio
async def test_list_notices_invalid_limit_422(async_client: httpx.AsyncClient) -> None:
    with patch("app.api.v1.notices.list_public_notices", new_callable=AsyncMock) as m:
        m.return_value = ([], None)
        resp = await async_client.get("/v1/notices", params={"limit": 0})
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_notices_operational_error_returns_503(async_client: httpx.AsyncClient) -> None:
    with patch("app.api.v1.notices.list_public_notices", new_callable=AsyncMock) as m:
        m.side_effect = OperationalError("SELECT 1", {}, Exception("db down"))
        resp = await async_client.get("/v1/notices")
        assert resp.status_code == 503
        assert "unavailable" in resp.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_get_notice_operational_error_returns_503(async_client: httpx.AsyncClient) -> None:
    nid = uuid.uuid4()
    with patch("app.api.v1.notices.get_public_notice_by_id", new_callable=AsyncMock) as m:
        m.side_effect = OperationalError("SELECT 1", {}, Exception("db down"))
        resp = await async_client.get(f"/v1/notices/{nid}")
        assert resp.status_code == 503
        assert "unavailable" in resp.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_semantic_search_operational_error_returns_503(async_client: httpx.AsyncClient) -> None:
    now = datetime.now(UTC)
    with patch("app.api.v1.notices.search_public_notices_semantic", new_callable=AsyncMock) as m:
        m.side_effect = OperationalError("SELECT 1", {}, Exception("db down"))
        resp = await async_client.post(
            "/v1/notices/search/semantic",
            json={
                "query": "scholarship",
                "college_external_id": "eng",
                "published_from": now.isoformat(),
                "published_to": now.isoformat(),
                "limit": 10,
            },
        )
        assert resp.status_code == 503
        assert "unavailable" in resp.json().get("detail", "").lower()
