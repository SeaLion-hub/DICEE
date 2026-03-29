"""유저 달력 이벤트(공지 고정) 추가·삭제."""

from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.contracts.calendar_contracts import UserCalendarEventCreate, UserCalendarEventCreated
from app.repositories import notice_repository, user_calendar_event_repository


class NoticeNotFoundForCalendarError(Exception):
    pass


class UserCalendarDuplicateError(Exception):
    pass


async def add_pinned_notice_event(
    session: AsyncSession,
    user_id: uuid.UUID,
    body: UserCalendarEventCreate,
) -> UserCalendarEventCreated:
    notice = await notice_repository.get_notice_by_id_with_relations(session, body.notice_id)
    if notice is None or notice.deleted_at is not None:
        raise NoticeNotFoundForCalendarError()
    title = (body.title or "").strip() or notice.title
    try:
        row = await user_calendar_event_repository.create_for_user(
            session,
            user_id=user_id,
            notice_id=body.notice_id,
            title=title[:512],
            start_at=body.start_at,
            end_at=body.end_at,
        )
    except IntegrityError as e:
        raise UserCalendarDuplicateError() from e
    return UserCalendarEventCreated(
        id=row.id,
        notice_id=row.notice_id,
        title=row.title,
        start_at=row.start_at,
        end_at=row.end_at,
    )


async def remove_user_event(session: AsyncSession, user_id: uuid.UUID, event_id: int) -> bool:
    return await user_calendar_event_repository.delete_for_user(session, user_id, event_id)
