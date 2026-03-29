"""시맨틱 검색 요청/응답 스키마."""

from datetime import datetime
from typing import Self

from pydantic import Field, model_validator

from app.schemas.base import BaseSchema
from app.schemas.notice_public import NoticeListItem


class NoticeSemanticSearchRequest(BaseSchema):
    college_external_id: str = Field(..., min_length=1, max_length=255)
    published_from: datetime
    published_to: datetime
    query: str = Field(..., min_length=1, max_length=4000)
    limit: int = Field(20, ge=1, le=100)

    @model_validator(mode="after")
    def published_order(self) -> Self:
        if self.published_to < self.published_from:
            raise ValueError("published_to must be >= published_from")
        return self


class NoticeSemanticSearchResponse(BaseSchema):
    """단일 페이지 결과. 커서 페이지네이션 없음(상위 N건만)."""

    items: list[NoticeListItem] = Field(
        ...,
        description="임베딩 유사도 상위 limit건(또는 그 미만). next_cursor 없음.",
    )
    limit: int = Field(..., description="요청에 echo. 최대 반환 건수 상한.")
