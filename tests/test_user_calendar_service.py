"""user_calendar_service branch coverage for pinned notice events."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.domain.contracts.calendar_contracts import UserCalendarEventCreate
from app.services.user_calendar_service import (
    NoticeNotFoundForCalendarError,
    UserCalendarDuplicateError,
    add_pinned_notice_event,
    remove_user_event,
)
from sqlalchemy.exc import IntegrityError


def _body(*, notice_id: uuid.UUID | None = None, title: str | None = "Pinned") -> UserCalendarEventCreate:
    return UserCalendarEventCreate(
        notice_id=notice_id or uuid.uuid4(),
        title=title,
        start_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        end_at=None,
    )


def _notice(*, deleted: bool = False, title: str = "Notice Title") -> MagicMock:
    notice = MagicMock()
    notice.deleted_at = datetime(2026, 1, 1, tzinfo=UTC) if deleted else None
    notice.title = title
    return notice


def _created_row(*, notice_id: uuid.UUID, title: str) -> MagicMock:
    row = MagicMock()
    row.id = 42
    row.notice_id = notice_id
    row.title = title
    row.start_at = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    row.end_at = None
    return row


@pytest.mark.asyncio
async def test_add_pinned_notice_event_missing_notice_raises() -> None:
    session = AsyncMock()
    body = _body()

    with patch(
        "app.services.user_calendar_service.notice_repository.get_notice_by_id_with_relations",
        new_callable=AsyncMock,
    ) as get_notice:
        get_notice.return_value = None
        with pytest.raises(NoticeNotFoundForCalendarError):
            await add_pinned_notice_event(session, uuid.uuid4(), body)


@pytest.mark.asyncio
async def test_add_pinned_notice_event_deleted_notice_raises() -> None:
    session = AsyncMock()
    body = _body()

    with patch(
        "app.services.user_calendar_service.notice_repository.get_notice_by_id_with_relations",
        new_callable=AsyncMock,
    ) as get_notice:
        get_notice.return_value = _notice(deleted=True)
        with pytest.raises(NoticeNotFoundForCalendarError):
            await add_pinned_notice_event(session, uuid.uuid4(), body)


@pytest.mark.asyncio
async def test_add_pinned_notice_event_blank_title_falls_back_to_notice_title() -> None:
    session = AsyncMock()
    user_id = uuid.uuid4()
    notice_id = uuid.uuid4()
    body = _body(notice_id=notice_id, title="   ")

    with (
        patch(
            "app.services.user_calendar_service.notice_repository.get_notice_by_id_with_relations",
            new_callable=AsyncMock,
        ) as get_notice,
        patch(
            "app.services.user_calendar_service.user_calendar_event_repository.create_for_user",
            new_callable=AsyncMock,
        ) as create_for_user,
    ):
        get_notice.return_value = _notice(title="Fallback Notice")
        create_for_user.return_value = _created_row(notice_id=notice_id, title="Fallback Notice")
        out = await add_pinned_notice_event(session, user_id, body)

    assert out.title == "Fallback Notice"
    create_for_user.assert_awaited_once()
    assert create_for_user.await_args.kwargs["title"] == "Fallback Notice"


@pytest.mark.asyncio
async def test_add_pinned_notice_event_truncates_long_service_title() -> None:
    session = AsyncMock()
    user_id = uuid.uuid4()
    notice_id = uuid.uuid4()
    body = MagicMock()
    body.notice_id = notice_id
    body.title = "x" * 600
    body.start_at = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    body.end_at = None

    with (
        patch(
            "app.services.user_calendar_service.notice_repository.get_notice_by_id_with_relations",
            new_callable=AsyncMock,
            return_value=_notice(),
        ),
        patch(
            "app.services.user_calendar_service.user_calendar_event_repository.create_for_user",
            new_callable=AsyncMock,
        ) as create_for_user,
    ):
        create_for_user.return_value = _created_row(notice_id=notice_id, title="x" * 512)
        out = await add_pinned_notice_event(session, user_id, body)

    assert out.title == "x" * 512
    assert create_for_user.await_args.kwargs["title"] == "x" * 512


@pytest.mark.asyncio
async def test_add_pinned_notice_event_integrity_error_becomes_duplicate_error() -> None:
    session = AsyncMock()
    body = _body()

    with (
        patch(
            "app.services.user_calendar_service.notice_repository.get_notice_by_id_with_relations",
            new_callable=AsyncMock,
            return_value=_notice(),
        ),
        patch(
            "app.services.user_calendar_service.user_calendar_event_repository.create_for_user",
            new_callable=AsyncMock,
        ) as create_for_user,
    ):
        create_for_user.side_effect = IntegrityError("INSERT", {}, Exception("duplicate"))
        with pytest.raises(UserCalendarDuplicateError):
            await add_pinned_notice_event(session, uuid.uuid4(), body)


@pytest.mark.asyncio
async def test_remove_user_event_returns_repository_result() -> None:
    session = AsyncMock()
    user_id = uuid.uuid4()

    with patch(
        "app.services.user_calendar_service.user_calendar_event_repository.delete_for_user",
        new_callable=AsyncMock,
    ) as delete_for_user:
        delete_for_user.return_value = False
        out = await remove_user_event(session, user_id, 7)

    assert out is False
    delete_for_user.assert_awaited_once_with(session, user_id, 7)
