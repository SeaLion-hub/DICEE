"""user_calendar_events CRUD."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLike
from app.models.user_calendar_event import UserCalendarEvent


async def list_for_user_in_range(
    session: AsyncSessionLike,
    user_id: uuid.UUID,
    *,
    range_start: datetime,
    range_end: datetime,
) -> list[UserCalendarEvent]:
    cond = and_(
        UserCalendarEvent.user_id == user_id,
        UserCalendarEvent.start_at < range_end,
        or_(UserCalendarEvent.end_at.is_(None), UserCalendarEvent.end_at >= range_start),
    )
    stmt = select(UserCalendarEvent).where(cond).order_by(UserCalendarEvent.start_at.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_for_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    notice_id: uuid.UUID,
    title: str,
    start_at: datetime,
    end_at: datetime | None,
) -> UserCalendarEvent:
    row = UserCalendarEvent(
        user_id=user_id,
        notice_id=notice_id,
        title=title,
        start_at=start_at,
        end_at=end_at,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def delete_for_user(session: AsyncSession, user_id: uuid.UUID, event_id: int) -> bool:
    stmt = delete(UserCalendarEvent).where(
        UserCalendarEvent.id == event_id,
        UserCalendarEvent.user_id == user_id,
    )
    result = await session.execute(stmt)
    return result.rowcount > 0
