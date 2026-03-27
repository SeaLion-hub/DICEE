"""공개 공지 API 응답 스키마."""

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.base import BaseSchema


class NoticeListItem(BaseSchema):
    """목록 1건. images·attachments·대용량 JSON은 목록에서 제외(defer)."""

    id: uuid.UUID
    college_external_id: str = Field(..., description="단과대 external_id")
    external_id: str
    title: str
    url: str | None = None
    published_at: datetime | None = None


class NoticeListResponse(BaseSchema):
    """키셋/오프셋 페이지네이션 목록."""

    items: list[NoticeListItem]
    next_cursor: str | None = None
    limit: int


class NoticeDetailResponse(NoticeListItem):
    """상세: 본문 URL·타임스탬프."""

    content_url: str | None = None
    created_at: datetime
    updated_at: datetime
