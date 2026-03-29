"""공개 공지 목록·상세 API (읽기 전용)."""

import logging
import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.core.deps import ReadOnlySessionDep
from app.core.exceptions import EmptySemanticQueryError
from app.domain.contracts.notice_public_contracts import NoticePublicDetailDTO, NoticePublicListItemDTO
from app.models.notice import Notice
from app.schemas.notice_public import NoticeDetailResponse, NoticeListItem, NoticeListResponse
from app.schemas.notice_semantic import NoticeSemanticSearchRequest, NoticeSemanticSearchResponse
from app.services.gemini_text_embedding import EmbeddingProviderError
from app.services.notice_public_service import (
    UnknownCollegeExternalIdError,
    get_public_notice_by_id,
    list_public_notices,
)
from app.services.notice_semantic_search_service import search_public_notices_semantic

router = APIRouter(prefix="/notices", tags=["notices"])
logger = logging.getLogger(__name__)

_NOTICES_DB_UNAVAILABLE_DETAIL = "Notice service temporarily unavailable. Try again later."
SEMANTIC_SEARCH_EMPTY_QUERY_DETAIL = "query must be non-empty"


def _list_dto_to_schema(d: NoticePublicListItemDTO) -> NoticeListItem:
    return NoticeListItem(
        id=d.id,
        college_external_id=d.college_external_id,
        external_id=d.external_id,
        title=d.title,
        url=d.url,
        published_at=d.published_at,
    )


def _notice_model_to_list_item(n: Notice) -> NoticeListItem:
    college = n.college
    ext = college.external_id if college is not None else ""
    return NoticeListItem(
        id=n.id,
        college_external_id=ext,
        external_id=n.external_id,
        title=n.title,
        url=n.url,
        published_at=n.published_at,
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
    offset: int = Query(
        0,
        ge=0,
        description="cursor 없을 때만 의미 있음. 다음 페이지는 응답의 next_cursor를 cursor로 넘기는 것을 권장.",
    ),
    cursor: str | None = Query(
        None,
        description="직전 응답의 next_cursor. 설정 시 키셋 페이지네이션(정렬 일치).",
    ),
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
    except (OperationalError, SQLAlchemyTimeoutError, TimeoutError) as e:
        logger.warning(
            "Public notices list DB error: %s",
            type(e).__name__,
            exc_info=True,
        )
        raise HTTPException(status_code=503, detail=_NOTICES_DB_UNAVAILABLE_DETAIL) from e
    return NoticeListResponse(
        items=[_list_dto_to_schema(x) for x in items],
        next_cursor=next_cursor,
        limit=limit,
    )


@router.post(
    "/search/semantic",
    response_model=NoticeSemanticSearchResponse,
    summary="시맨틱 검색(단일 페이지)",
    description=(
        "임베딩 유사도 상위 N건을 한 번에 반환한다. "
        "목록 API와 달리 next_cursor·페이지네이션 없음. "
        "자세한 계약은 docs/decisions/notice-semantic-search-contract.md."
    ),
)
async def semantic_search_notices(
    session: ReadOnlySessionDep,
    body: NoticeSemanticSearchRequest,
) -> NoticeSemanticSearchResponse:
    try:
        rows = await search_public_notices_semantic(
            session,
            college_external_id=body.college_external_id,
            published_from=body.published_from,
            published_to=body.published_to,
            query=body.query,
            limit=body.limit,
        )
    except UnknownCollegeExternalIdError:
        raise HTTPException(status_code=404, detail="College not found") from None
    except EmptySemanticQueryError:
        raise HTTPException(status_code=400, detail=SEMANTIC_SEARCH_EMPTY_QUERY_DETAIL) from None
    except EmbeddingProviderError:
        raise HTTPException(status_code=503, detail="Embedding service unavailable") from None
    except ValueError:
        logger.warning(
            "Semantic search unexpected ValueError (client response masked)",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error") from None
    except (OperationalError, SQLAlchemyTimeoutError, TimeoutError) as e:
        logger.warning(
            "Semantic search DB error: %s",
            type(e).__name__,
            exc_info=True,
        )
        raise HTTPException(status_code=503, detail=_NOTICES_DB_UNAVAILABLE_DETAIL) from e
    return NoticeSemanticSearchResponse(
        items=[_notice_model_to_list_item(n) for n in rows],
        limit=body.limit,
    )


@router.get("/{notice_id}", response_model=NoticeDetailResponse)
async def get_notice(
    notice_id: uuid.UUID,
    session: ReadOnlySessionDep,
) -> NoticeDetailResponse:
    try:
        detail = await get_public_notice_by_id(session, notice_id)
    except (OperationalError, SQLAlchemyTimeoutError, TimeoutError) as e:
        logger.warning(
            "Public notice detail DB error: %s",
            type(e).__name__,
            exc_info=True,
        )
        raise HTTPException(status_code=503, detail=_NOTICES_DB_UNAVAILABLE_DETAIL) from e
    if detail is None:
        raise HTTPException(status_code=404, detail="Notice not found")
    return _detail_dto_to_schema(detail)
