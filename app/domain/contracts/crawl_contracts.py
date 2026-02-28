"""Crawl/통계 도메인 계약. Repository는 프레젠테이션(isoformat 등)을 수행하지 않음."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class NoticeDraft:
    """크롤러↔리포지토리 간 upsert용 1건. DB/API 스키마와 독립적인 도메인 계약."""

    college_id: uuid.UUID
    external_id: str
    title: str
    url: str | None
    content_url: str | None  # 업로드 실패/스풀 경로로 None 가능
    images: list[dict[str, Any]] | None = None
    attachments: list[dict[str, Any]] = field(default_factory=list)
    content_hash: str = ""
    published_at: datetime | None = None


@dataclass(frozen=True)
class CrawlRunRow:
    """최근 크롤 실행 1건. Repository가 Entity에서 채우는 순수 데이터(datetime 그대로)."""

    college_code: str
    started_at: datetime | None
    finished_at: datetime | None
    status: str
    notices_upserted: int
    error_message: str | None


class CrawlStatsQueryPort(Protocol):
    """크롤 통계 조회 포트. Session은 호출자(서비스)가 전달(실용적 포트)."""

    async def fetch_recent(
        self, session: AsyncSession, limit: int
    ) -> list[CrawlRunRow]: ...


class AsyncNoticeRepositoryPort(Protocol):
    """Notice bulk upsert 비동기 포트. Session은 호출자가 전달."""

    async def upsert_bulk(
        self, session: AsyncSession, drafts: Sequence[NoticeDraft]
    ) -> list[uuid.UUID]: ...


class SyncNoticeRepositoryPort(Protocol):
    """Notice bulk upsert 동기 포트. Session은 호출자가 전달."""

    def upsert_bulk_sync(
        self, session: Session, drafts: Sequence[NoticeDraft]
    ) -> list[uuid.UUID]: ...
