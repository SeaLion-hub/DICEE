"""5단계 인증 필요 API: JWT·Blocklist 목 + 서비스 패치로 라우터·계약 회귀 검증."""

from __future__ import annotations

import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from app.core.deps import get_redis_blocklist
from app.domain.contracts.calendar_contracts import UserCalendarEventCreated
from app.domain.contracts.notice_public_contracts import NoticePublicListItemDTO
from app.domain.contracts.user_profile_matching_contracts import (
    UserMeResponse,
    UserProfileForMatching,
)
from app.services.auth_service import create_jwt_pair
from app.services.calendar_service import CalendarRangeError
from fastapi import Request


@contextmanager
def _blocklist_override_ok(app: object) -> Generator[None, None, None]:
    """verify_access_token이 Redis exists=False를 보도록 Blocklist 클라이언트 목 주입."""

    def _fake_redis(_request: Request) -> MagicMock:
        m = MagicMock()
        m.exists = AsyncMock(return_value=0)
        return m

    app.dependency_overrides[get_redis_blocklist] = _fake_redis  # type: ignore[attr-defined]
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_redis_blocklist, None)  # type: ignore[attr-defined]


def _fixed_user_id() -> uuid.UUID:
    return uuid.UUID("00000000-0000-7000-8000-0000000000a5")


def _auth_headers(user_id: uuid.UUID | None = None) -> dict[str, str]:
    uid = user_id or _fixed_user_id()
    access_token, _ = create_jwt_pair(user_id=uid)
    return {"Authorization": f"Bearer {access_token}"}


@pytest.mark.asyncio
async def test_get_users_me_returns_200(async_client: httpx.AsyncClient, api_app) -> None:
    uid = _fixed_user_id()
    body = UserMeResponse(
        id=uid,
        email="me@example.com",
        name="Me",
        profile=UserProfileForMatching(department_codes=["yu_college_engineering"], grades=["3"]),
        matching_eligible=True,
    )
    with _blocklist_override_ok(api_app):
        with patch("app.api.v1.users.user_profile_service.get_me", new_callable=AsyncMock) as m:
            m.return_value = body
            resp = await async_client.get("/v1/users/me", headers=_auth_headers(uid))
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(uid)
    assert data["email"] == "me@example.com"
    assert data["matching_eligible"] is True
    assert "profile" in data


@pytest.mark.asyncio
async def test_patch_users_me_returns_200(async_client: httpx.AsyncClient, api_app) -> None:
    uid = _fixed_user_id()
    body = UserMeResponse(
        id=uid,
        email="me@example.com",
        name="Me",
        profile=UserProfileForMatching(department_codes=["yu_college_engineering"], grades=["3"]),
        matching_eligible=True,
    )
    patch_json = {"grades": ["3"], "department_codes": ["yu_college_engineering"]}
    with _blocklist_override_ok(api_app):
        with patch("app.api.v1.users.user_profile_service.patch_me", new_callable=AsyncMock) as m:
            m.return_value = body
            resp = await async_client.patch("/v1/users/me", headers=_auth_headers(uid), json=patch_json)
    assert resp.status_code == 200
    assert resp.json()["matching_eligible"] is True


@pytest.mark.asyncio
async def test_get_notices_matched_returns_200(async_client: httpx.AsyncClient, api_app) -> None:
    uid = _fixed_user_id()
    nid = uuid.uuid4()
    item = NoticePublicListItemDTO(
        id=nid,
        college_external_id="eng",
        external_id="42",
        title="t",
        url=None,
        published_at=None,
    )
    with _blocklist_override_ok(api_app):
        with patch("app.api.v1.notices_matched.list_matched_notices", new_callable=AsyncMock) as m:
            m.return_value = ([item], "next-c", False)
            resp = await async_client.get("/v1/notices/matched", headers=_auth_headers(uid))
    assert resp.status_code == 200
    data = resp.json()
    assert data["requires_profile"] is False
    assert data["next_cursor"] == "next-c"
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == str(nid)


@pytest.mark.asyncio
async def test_get_calendar_events_returns_200(async_client: httpx.AsyncClient, api_app) -> None:
    uid = _fixed_user_id()
    rs = datetime(2026, 3, 1, tzinfo=UTC)
    re = datetime(2026, 3, 31, 23, 59, 59, tzinfo=UTC)
    payload = {
        "range_start": rs,
        "range_end": re,
        "notice_schedules": [],
        "user_events": [],
    }
    with _blocklist_override_ok(api_app):
        with patch("app.api.v1.calendar.build_calendar_payload", new_callable=AsyncMock) as m:
            m.return_value = payload
            resp = await async_client.get(
                "/v1/calendar/events",
                headers=_auth_headers(uid),
                params={"year": 2026, "month": 3},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert "range_start" in data and "range_end" in data
    assert data["notice_schedules"] == []
    assert data["user_events"] == []


@pytest.mark.asyncio
async def test_get_calendar_events_invalid_range_returns_400(async_client: httpx.AsyncClient, api_app) -> None:
    uid = _fixed_user_id()
    with _blocklist_override_ok(api_app):
        with patch("app.api.v1.calendar.build_calendar_payload", new_callable=AsyncMock) as m:
            m.side_effect = CalendarRangeError("year and month required together")
            resp = await async_client.get(
                "/v1/calendar/events",
                headers=_auth_headers(uid),
                params={"year": 2026},
            )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_calendar_feed_ics_returns_text_calendar(async_client: httpx.AsyncClient, api_app) -> None:
    uid = _fixed_user_id()
    rs = datetime(2026, 3, 1, tzinfo=UTC)
    re = datetime(2026, 3, 31, 23, 59, 59, tzinfo=UTC)
    payload = {
        "range_start": rs,
        "range_end": re,
        "notice_schedules": [],
        "user_events": [],
    }
    with _blocklist_override_ok(api_app):
        with patch("app.api.v1.calendar.build_calendar_payload", new_callable=AsyncMock) as m:
            m.return_value = payload
            resp = await async_client.get(
                "/v1/calendar/feed.ics",
                headers=_auth_headers(uid),
                params={"year": 2026, "month": 3},
            )
    assert resp.status_code == 200
    assert "text/calendar" in (resp.headers.get("content-type") or "")
    assert b"BEGIN:VCALENDAR" in resp.content


@pytest.mark.asyncio
async def test_post_user_calendar_event_returns_200(async_client: httpx.AsyncClient, api_app) -> None:
    uid = _fixed_user_id()
    nid = uuid.uuid4()
    start = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    created = UserCalendarEventCreated(
        id=99,
        notice_id=nid,
        title="Pinned",
        start_at=start,
        end_at=None,
    )
    json_body = {
        "notice_id": str(nid),
        "title": "Pinned",
        "start_at": start.isoformat().replace("+00:00", "Z"),
    }
    with _blocklist_override_ok(api_app):
        with patch("app.api.v1.calendar.add_pinned_notice_event", new_callable=AsyncMock) as m:
            m.return_value = created
            resp = await async_client.post(
                "/v1/users/me/calendar/events",
                headers=_auth_headers(uid),
                json=json_body,
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 99
    assert data["notice_id"] == str(nid)


@pytest.mark.asyncio
async def test_delete_user_calendar_event_returns_204(async_client: httpx.AsyncClient, api_app) -> None:
    uid = _fixed_user_id()
    with _blocklist_override_ok(api_app):
        with patch("app.api.v1.calendar.remove_user_event", new_callable=AsyncMock) as m:
            m.return_value = True
            resp = await async_client.delete(
                "/v1/users/me/calendar/events/7",
                headers=_auth_headers(uid),
            )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_user_calendar_event_not_found_returns_404(async_client: httpx.AsyncClient, api_app) -> None:
    uid = _fixed_user_id()
    with _blocklist_override_ok(api_app):
        with patch("app.api.v1.calendar.remove_user_event", new_callable=AsyncMock) as m:
            m.return_value = False
            resp = await async_client.delete(
                "/v1/users/me/calendar/events/999",
                headers=_auth_headers(uid),
            )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_users_me_without_auth_returns_401(async_client: httpx.AsyncClient, api_app) -> None:
    with _blocklist_override_ok(api_app):
        resp = await async_client.get("/v1/users/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_users_me_user_not_found_returns_404(async_client: httpx.AsyncClient, api_app) -> None:
    from app.core.exceptions import UserNotFoundError

    uid = _fixed_user_id()
    with _blocklist_override_ok(api_app):
        with patch("app.api.v1.users.user_profile_service.get_me", new_callable=AsyncMock) as m:
            m.side_effect = UserNotFoundError()
            resp = await async_client.get("/v1/users/me", headers=_auth_headers(uid))
    assert resp.status_code == 404
