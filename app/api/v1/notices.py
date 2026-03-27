"""공개 공지 목록·상세 API (읽기 전용)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import ReadOnlySessionDep
from app.domain.contracts.notice_public_contracts import NoticePublicDetailDTO, NoticePublicListItemDTO
from app.schemas.notice_public import NoticeDetailResponse, NoticeListResponse, NoticeListItem
from app.services.notice_public_service import (
    UnknownCollegeExternalIdError,
    get_public_notice_by_id,
    list_public_notices,
)

router = APIRouter(prefix="/notices", tags=["notices"])


def _list_dto_to_schema(d: NoticePublicListItemDTO) -> NoticeListItem:
    return NoticeListItem(
        id=d.id,
        college_external_id=d.college_external_id,
        external_id=d.external_id,
        title=d.title,
        url=d.url,
        published_at=d.published_at,
    )


def _detail_dto_to_schema(d: NoticePublicDetailDTO) -> NoticeDetailResponse:
    return NoticeDetailResponse(
        id=d.id,
        college_external_id=d.college_external_id,
        external_id=d.external_id,
        title=d.title,
        url=d.url,
        published_at=d.published_at,
        content_url=d.content_url,
        created_at=d.created_at,
        updated_at=d.updated_at,
    )


@router.get("", response_model=NoticeListResponse)
async def list_notices(
    session: ReadOnlySessionDep,
    limit: int = Query(20, ge=1, le=100, description="페이지 크기"),
    offset: int = Query(0, ge=0, description="cursor 미사용 시 오프셋"),
    cursor: str | None = Query(None, description="다음 페이지 커서(이전 응답의 next_cursor)"),
    college_external_id: str | None = Query(
        None,
        max_length=255,
        description="단과대 external_id로 필터. 없으면 전체.",
    ),
) -> NoticeListResponse:
    try:
        items, next_cursor = await list_public_notices(
            session,
            limit=limit,
            offset=offset,
            cursor=cursor,
            college_external_id=college_external_id,
        )
    except UnknownCollegeExternalIdError:
        raise HTTPException(status_code=404, detail="College not found") from None
    return NoticeListResponse(
        items=[_list_dto_to_schema(x) for x in items],
        next_cursor=next_cursor,
        limit=limit,
    )


@router.get("/{notice_id}", response_model=NoticeDetailResponse)
async def get_notice(
    notice_id: uuid.UUID,
    session: ReadOnlySessionDep,
) -> NoticeDetailResponse:
    detail = await get_public_notice_by_id(session, notice_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Notice not found")
    return _detail_dto_to_schema(detail)
