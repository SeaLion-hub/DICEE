"""인증 필요: 맞춤(매칭) 공지 목록."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.api.v1.auth import VerifiedAccessDep
from app.core.deps import ReadOnlySessionDep
from app.core.exceptions import UserNotFoundError
from app.domain.contracts.notice_public_contracts import NoticePublicListItemDTO
from app.schemas.notice_public import MatchedNoticeListResponse, NoticeListItem
from app.services.matched_notice_service import list_matched_notices

router = APIRouter(prefix="/notices", tags=["notices"])
logger = logging.getLogger(__name__)

_DB_UNAVAILABLE = "Notice service temporarily unavailable. Try again later."


def _dto_to_item(d: NoticePublicListItemDTO) -> NoticeListItem:
    return NoticeListItem(
        id=d.id,
        college_external_id=d.college_external_id,
        external_id=d.external_id,
        title=d.title,
        url=d.url,
        published_at=d.published_at,
    )


@router.get("/matched", response_model=MatchedNoticeListResponse)
async def list_matched(
    session: ReadOnlySessionDep,
    access: VerifiedAccessDep,
    limit: int = Query(20, ge=1, le=50, description="페이지 크기 (기본 20, 최대 50)"),
    cursor: str | None = Query(None, description="이전 응답의 next_cursor"),
) -> MatchedNoticeListResponse:
    try:
        items, next_cursor, requires_profile = await list_matched_notices(
            session,
            access.user_id,
            limit=limit,
            cursor=cursor,
        )
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found") from None
    except (OperationalError, SQLAlchemyTimeoutError, TimeoutError) as e:
        logger.warning("list_matched DB error: %s", type(e).__name__, exc_info=True)
        raise HTTPException(status_code=503, detail=_DB_UNAVAILABLE) from e
    return MatchedNoticeListResponse(
        items=[_dto_to_item(x) for x in items],
        next_cursor=next_cursor,
        limit=limit,
        requires_profile=requires_profile,
    )
