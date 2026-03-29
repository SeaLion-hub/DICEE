"""달력 구간 파싱·매칭 일정·유저 일정 조립."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from app.core.database import AsyncSessionLike
from app.core.exceptions import UserNotFoundError
from app.repositories import notice_schedule_repository, user_calendar_event_repository, user_repository
from app.services import matching_service
from app.services.user_profile_service import profile_from_user_profile_json

TZ_SEOUL = ZoneInfo("Asia/Seoul")


class CalendarRangeError(Exception):
    """year/month 또는 from/to가 잘못되었거나 동시에 빠짐."""

    pass


@dataclass(frozen=True, slots=True)
class CalendarRange:
    start: datetime
    end: datetime


def parse_calendar_range(
    *,
    year: int | None,
    month: int | None,
    date_from: str | None,
    date_to: str | None,
) -> CalendarRange:
    """
    ADR §6.2: from/to가 있으면 구간 모드 우선(반열린 [start, end)로 해석).
    없으면 year+month 필수.
    """
    if date_from is not None or date_to is not None:
        if not date_from or not date_to:
            raise CalendarRangeError("from and to are both required for range mode")
        try:
            d0 = date.fromisoformat(date_from.strip())
            d1 = date.fromisoformat(date_to.strip())
        except ValueError as e:
            raise CalendarRangeError("from and to must be ISO 8601 dates (YYYY-MM-DD)") from e
        start = datetime.combine(d0, time.min, tzinfo=TZ_SEOUL).astimezone(UTC)
        end = datetime.combine(d1, time.min, tzinfo=TZ_SEOUL).astimezone(UTC)
        if start >= end:
            raise CalendarRangeError("from must be before to")
        return CalendarRange(start=start, end=end)

    if year is None or month is None:
        raise CalendarRangeError("year and month are required when from/to are not set")
    if month < 1 or month > 12:
        raise CalendarRangeError("month must be 1–12")
    if year < 1970 or year > 2100:
        raise CalendarRangeError("year out of supported range")
    start = datetime(year, month, 1, 0, 0, 0, tzinfo=TZ_SEOUL).astimezone(UTC)
    if month == 12:
        end = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=TZ_SEOUL).astimezone(UTC)
    else:
        end = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=TZ_SEOUL).astimezone(UTC)
    return CalendarRange(start=start, end=end)


async def build_calendar_payload(
    session: AsyncSessionLike,
    user_id: uuid.UUID,
    *,
    year: int | None,
    month: int | None,
    date_from: str | None,
    date_to: str | None,
) -> dict[str, Any]:
    user = await user_repository.get_by_id(session, user_id)
    if user is None:
        raise UserNotFoundError()
    cr = parse_calendar_range(year=year, month=month, date_from=date_from, date_to=date_to)
    profile = profile_from_user_profile_json(user.profile_json)
    eligible = matching_service.matching_eligible(profile)

    notice_parts: list[dict[str, Any]] = []
    if eligible:
        rows = await notice_schedule_repository.list_schedules_overlapping_range(
            session,
            range_start=cr.start,
            range_end=cr.end,
        )
        for ns, notice in rows:
            if not matching_service.notice_row_matches_profile(
                ai_extracted_json=notice.ai_extracted_json,
                profile=profile,
            ):
                continue
            college = notice.college
            notice_parts.append(
                {
                    "schedule_id": ns.id,
                    "notice_id": notice.id,
                    "college_external_id": college.external_id if college else "",
                    "title": notice.title,
                    "schedule_type": ns.schedule_type,
                    "start_at": ns.start_at,
                    "end_at": ns.end_at,
                    "is_all_day": ns.is_all_day,
                    "schedule_text_fallback": ns.schedule_text_fallback,
                }
            )

    urows = await user_calendar_event_repository.list_for_user_in_range(
        session,
        user_id,
        range_start=cr.start,
        range_end=cr.end,
    )
    user_parts = [
        {
            "id": e.id,
            "notice_id": str(e.notice_id),
            "title": e.title,
            "start_at": e.start_at,
            "end_at": e.end_at,
        }
        for e in urows
    ]

    return {
        "range_start": cr.start,
        "range_end": cr.end,
        "notice_schedules": notice_parts,
        "user_events": user_parts,
    }
