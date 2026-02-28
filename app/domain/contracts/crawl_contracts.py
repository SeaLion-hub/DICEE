"""Crawl/통계 도메인 계약. Repository는 프레젠테이션(isoformat 등)을 수행하지 않음."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, NotRequired, Protocol, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session


class LinkItem(TypedDict):
    """크롤 링크 1건. 리스트 목록/스크랩 입력. url 필수, no는 선택."""

    url: str
    no: NotRequired[str]


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


@dataclass(frozen=True)
class CrawlRunItem:
    """크롤 통계 1건(서비스 반환용). started_at/finished_at는 이미 문자열(isoformat)."""

    college_code: str
    started_at: str | None
    finished_at: str | None
    status: str
    notices_upserted: int
    has_error: bool


@dataclass(frozen=True)
class CrawlStatsResult:
    """크롤 통계 조회 결과. 라우터에서 CrawlStatsResponse로 변환."""

    runs: list[CrawlRunItem]
    limit: int


class CrawlStatsQueryPort(Protocol):
    """크롤 통계 조회 포트. Session은 호출자(서비스)가 전달(실용적 포트)."""

    async def fetch_recent(self, session: AsyncSession, limit: int) -> list[CrawlRunRow]: ...


class AsyncNoticeRepositoryPort(Protocol):
    """Notice bulk upsert 비동기 포트. Session은 호출자가 전달."""

    async def upsert_bulk(self, session: AsyncSession, drafts: Sequence[NoticeDraft]) -> list[uuid.UUID]: ...


class SyncNoticeRepositoryPort(Protocol):
    """Notice bulk upsert 동기 포트. Session은 호출자가 전달."""

    def upsert_bulk_sync(self, session: Session, drafts: Sequence[NoticeDraft]) -> list[uuid.UUID]: ...
