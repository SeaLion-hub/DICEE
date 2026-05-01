"""notice_schedules 조회·동기 교체 (AI 워커)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, delete, insert, inspect, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload

from app.core.database import AsyncSessionLike
from app.domain.contracts.ai_extraction import ScheduleItem
from app.models.notice import Notice
from app.models.notice_schedule import NoticeSchedule


def _schedule_row_dict(notice_id: uuid.UUID, item: ScheduleItem) -> dict[str, Any] | None:
    st = item.kind.value[:32]
    now = datetime.now(UTC)
    if item.starts_at is not None:
        fb = (item.label or "").strip()[:255] or None
        return {
            "notice_id": notice_id,
            "schedule_type": st,
            "start_at": item.starts_at,
            "end_at": item.ends_at,
            "is_all_day": item.is_all_day,
            "is_tbd": False,
            "is_always_open": False,
            "schedule_text_fallback": fb,
            "created_at": now,
            "updated_at": now,
        }
    raw = item.date_raw or item.start_date_raw or item.end_date_raw
    if raw:
        fb = str(raw).strip()[:255]
    elif item.label:
        fb = str(item.label).strip()[:255]
    else:
        return None
    return {
        "notice_id": notice_id,
        "schedule_type": st,
        "start_at": None,
        "end_at": None,
        "is_all_day": False,
        "is_tbd": True,
        "is_always_open": False,
        "schedule_text_fallback": fb,
        "created_at": now,
        "updated_at": now,
    }


def replace_notice_schedules_sync(
    session: Session,
    notice_id: uuid.UUID,
    schedules: list[ScheduleItem],
) -> None:
    """해당 공지의 일정 행을 AI schedules로 완전 교체."""
    session.execute(delete(NoticeSchedule).where(NoticeSchedule.notice_id == notice_id))
    rows: list[dict[str, Any]] = []
    for item in schedules:
        row = _schedule_row_dict(notice_id, item)
        if row is not None:
            rows.append(row)
    if rows:
        session.bulk_insert_mappings(inspect(NoticeSchedule).mapper, rows)
    session.flush()


async def replace_notice_schedules(
    session: AsyncSession,
    notice_id: uuid.UUID,
    schedules: list[ScheduleItem],
) -> None:
    """해당 공지의 일정 행을 AI schedules로 완전 교체(비동기 관리자/API 경로)."""
    await session.execute(delete(NoticeSchedule).where(NoticeSchedule.notice_id == notice_id))
    rows: list[dict[str, Any]] = []
    for item in schedules:
        row = _schedule_row_dict(notice_id, item)
        if row is not None:
            rows.append(row)
    if rows:
        await session.execute(insert(NoticeSchedule), rows)
    await session.flush()


async def list_schedules_overlapping_range(
    session: AsyncSessionLike,
    *,
    range_start: datetime,
    range_end: datetime,
) -> list[tuple[NoticeSchedule, Notice]]:
    """
    구간 [range_start, range_end)와 시간이 겹치는 일정.
    is_tbd·start_at NULL 행은 제외(달력에 시각 없음).
    """
    overlap = and_(
        NoticeSchedule.is_tbd.is_(False),
        NoticeSchedule.start_at.isnot(None),
        NoticeSchedule.start_at < range_end,
        or_(NoticeSchedule.end_at.is_(None), NoticeSchedule.end_at >= range_start),
    )
    stmt = (
        select(NoticeSchedule, Notice)
        .join(Notice, Notice.id == NoticeSchedule.notice_id)
        .where(
            Notice.deleted_at.is_(None),
            overlap,
        )
        .options(selectinload(Notice.college))
        .order_by(NoticeSchedule.start_at.asc())
    )
    result = await session.execute(stmt)
    return [(ns, n) for ns, n in result.all()]
