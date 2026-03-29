"""달력 조회·ICS·유저 고정 일정."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.api.v1.auth import VerifiedAccessDep
from app.core.deps import ReadOnlySessionDep, SessionDep
from app.core.exceptions import UserNotFoundError
from app.schemas.calendar import (
    CalendarEventsResponse,
    CalendarNoticeScheduleItem,
    CalendarUserEventItem,
    UserCalendarEventCreate,
    UserCalendarEventCreated,
)
from app.services.calendar_ics_service import build_ics_from_calendar_payload
from app.services.calendar_service import CalendarRangeError, build_calendar_payload
from app.services.user_calendar_service import (
    NoticeNotFoundForCalendarError,
    UserCalendarDuplicateError,
    add_pinned_notice_event,
    remove_user_event,
)

feed_router = APIRouter(prefix="/calendar", tags=["calendar"])
user_cal_router = APIRouter(prefix="/users/me/calendar", tags=["calendar"])
logger = logging.getLogger(__name__)

_DB_UNAVAILABLE = "Calendar service temporarily unavailable. Try again later."


@feed_router.get("/events", response_model=CalendarEventsResponse)
async def get_calendar_events(
    session: ReadOnlySessionDep,
    access: VerifiedAccessDep,
    year: int | None = Query(None, ge=1970, le=2100),
    month: int | None = Query(None, ge=1, le=12),
    date_from: str | None = Query(None, alias="from", description="ISO 날짜 YYYY-MM-DD (구간 모드)"),
    date_to: str | None = Query(None, alias="to", description="ISO 날짜 YYYY-MM-DD (구간 모드)"),
) -> CalendarEventsResponse:
    try:
        raw = await build_calendar_payload(
            session,
            access.user_id,
            year=year,
            month=month,
            date_from=date_from,
            date_to=date_to,
        )
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found") from None
    except CalendarRangeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except (OperationalError, SQLAlchemyTimeoutError, TimeoutError) as e:
        logger.warning("get_calendar_events DB error: %s", type(e).__name__, exc_info=True)
        raise HTTPException(status_code=503, detail=_DB_UNAVAILABLE) from e

    ns_items = [CalendarNoticeScheduleItem.model_validate(x) for x in raw["notice_schedules"]]
    ue_items = [CalendarUserEventItem.model_validate(x) for x in raw["user_events"]]
    return CalendarEventsResponse(
        range_start=raw["range_start"],
        range_end=raw["range_end"],
        notice_schedules=ns_items,
        user_events=ue_items,
    )


@feed_router.get("/feed.ics")
async def get_calendar_feed_ics(
    session: ReadOnlySessionDep,
    access: VerifiedAccessDep,
    year: int | None = Query(None, ge=1970, le=2100),
    month: int | None = Query(None, ge=1, le=12),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
) -> Response:
    try:
        raw = await build_calendar_payload(
            session,
            access.user_id,
            year=year,
            month=month,
            date_from=date_from,
            date_to=date_to,
        )
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found") from None
    except CalendarRangeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except (OperationalError, SQLAlchemyTimeoutError, TimeoutError) as e:
        logger.warning("get_calendar_feed_ics DB error: %s", type(e).__name__, exc_info=True)
        raise HTTPException(status_code=503, detail=_DB_UNAVAILABLE) from e

    cal_uid = str(access.user_id)
    body = build_ics_from_calendar_payload(raw, calendar_uid=cal_uid)
    return Response(
        content=body.encode("utf-8"),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="dicee-calendar.ics"'},
    )


@user_cal_router.post("/events", response_model=UserCalendarEventCreated)
async def post_user_calendar_event(
    session: SessionDep,
    access: VerifiedAccessDep,
    body: UserCalendarEventCreate,
) -> UserCalendarEventCreated:
    try:
        out = await add_pinned_notice_event(session, access.user_id, body)
        await session.commit()
        return out
    except NoticeNotFoundForCalendarError:
        await session.rollback()
        raise HTTPException(status_code=404, detail="Notice not found") from None
    except UserCalendarDuplicateError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="This notice is already on your calendar",
        ) from None
    except (OperationalError, SQLAlchemyTimeoutError, TimeoutError) as e:
        await session.rollback()
        logger.warning("post_user_calendar_event DB error: %s", type(e).__name__, exc_info=True)
        raise HTTPException(status_code=503, detail=_DB_UNAVAILABLE) from e


@user_cal_router.delete("/events/{event_id}", status_code=204, response_model=None)
async def delete_user_calendar_event(
    session: SessionDep,
    access: VerifiedAccessDep,
    event_id: int,
) -> None:
    try:
        ok = await remove_user_event(session, access.user_id, event_id)
        if not ok:
            await session.rollback()
            raise HTTPException(status_code=404, detail="Calendar event not found") from None
        await session.commit()
    except HTTPException:
        raise
    except (OperationalError, SQLAlchemyTimeoutError, TimeoutError) as e:
        await session.rollback()
        logger.warning("delete_user_calendar_event DB error: %s", type(e).__name__, exc_info=True)
        raise HTTPException(status_code=503, detail=_DB_UNAVAILABLE) from e
