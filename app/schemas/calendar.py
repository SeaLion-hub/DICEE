"""달력 API 응답·요청 re-export (본문 모델은 domain.contracts.calendar_contracts)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.contracts.calendar_contracts import UserCalendarEventCreate, UserCalendarEventCreated

__all__ = [
    "CalendarEventsResponse",
    "CalendarNoticeScheduleItem",
    "CalendarUserEventItem",
    "UserCalendarEventCreate",
    "UserCalendarEventCreated",
]


class CalendarNoticeScheduleItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    schedule_id: uuid.UUID
    notice_id: uuid.UUID
    college_external_id: str = ""
    title: str
    schedule_type: str
    start_at: datetime | None = None
    end_at: datetime | None = None
    is_all_day: bool = False
    schedule_text_fallback: str | None = None


class CalendarUserEventItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    notice_id: uuid.UUID
    title: str
    start_at: datetime
    end_at: datetime | None = None


class CalendarEventsResponse(BaseModel):
    range_start: datetime = Field(description="조회 구간 시작 (UTC)")
    range_end: datetime = Field(description="조회 구간 끝 (UTC, 반열린)")
    notice_schedules: list[CalendarNoticeScheduleItem]
    user_events: list[CalendarUserEventItem]
