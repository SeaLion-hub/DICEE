"""Runner가 Celery·파이프라인에 노출하는 정규화 패킷 (Pydantic v2)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class NoticeRunnerDocument(BaseModel):
    """수집·처리 파이프라인 경계용 공지 1건 스냅샷 (DB upsert 전 단계)."""

    kind: Literal["notice_document"] = "notice_document"
    college_id: uuid.UUID
    external_id: str
    title: str
    url: str | None = None
    content_url: str | None = None
    images: list[dict[str, Any]] | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    content_hash: str = ""
    published_at: datetime | None = None


class CrawlRunnerFailure(BaseModel):
    """리스트/상세 단계 실패 보고. 파이프라인이 원인 코드로 분기 가능."""

    kind: Literal["crawl_failure"] = "crawl_failure"
    phase: str
    message: str
    detail_url: str | None = None
    event_code: str | None = None


class CrawlRunnerCheckpoint(BaseModel):
    """체크포인트 이벤트 (processed_count 등). 선택적 yield."""

    kind: Literal["checkpoint"] = "checkpoint"
    processed_count: int
    pointer: dict[str, Any] = Field(default_factory=dict)


CrawlRunnerPacket = NoticeRunnerDocument | CrawlRunnerFailure | CrawlRunnerCheckpoint
