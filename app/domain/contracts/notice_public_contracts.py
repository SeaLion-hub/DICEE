"""공개 공지 조회용 서비스 출력 DTO. services는 schemas 대신 본 모듈만 참조."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class NoticePublicListItemDTO:
    id: uuid.UUID
    college_external_id: str
    external_id: str
    title: str
    url: str | None
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class NoticePublicDetailDTO:
    id: uuid.UUID
    college_external_id: str
    external_id: str
    title: str
    url: str | None
    published_at: datetime | None
    content_url: str | None
    created_at: datetime
    updated_at: datetime
