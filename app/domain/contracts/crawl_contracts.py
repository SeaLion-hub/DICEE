"""Crawl/통계 도메인 계약. Repository는 프레젠테이션(isoformat 등)을 수행하지 않음."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, NotRequired, Protocol, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session


class CrawlPhase(str, Enum):
    """크롤 실행 단계. 실패 시 로그/Sentry에서 구분용."""

    LIST = "list"
    SCRAPE = "scrape"
    UPSERT = "upsert"


# 관측성: 단계별 event_code. 로깅·Sentry 태그 통일.
EVENT_LIST_FETCH_FAILED = "CRAWL_LIST_FETCH_FAILED"
EVENT_PARSE_FAILED = "CRAWL_PARSE_FAILED"
EVENT_UPSERT_FAILED = "CRAWL_UPSERT_FAILED"


@dataclass(frozen=True)
class CrawlJobFailed:
    """크롤 작업 실패 이벤트. failure_publisher로 발행 후 컴포지트 핸들러에서 DB/Redis 처리."""

    run_id: uuid.UUID
    task_id: str
    college_code: str
    error_message: str
    reason_code: str


class LinkItem(TypedDict):
    """크롤 링크 1건. 리스트 목록/스크랩 입력. url 필수, no·title_hint는 선택."""

    url: str
    no: NotRequired[str]
    title_hint: NotRequired[str]


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
class CrawlLogContext:
    """크롤/파싱 실패 로그·Sentry용 컨텍스트. college_code/run_id/task_id/phase를 한 객체로 전달."""

    college_code: str
    run_id: uuid.UUID | None = None
    task_id: str | None = None
    phase: CrawlPhase | None = None
    event_code: str = ""

    def extra_for_log(self) -> dict[str, str]:
        """로그 extra·Sentry 태그용 dict. 빈 값은 빈 문자열로 통일."""
        out: dict[str, str] = {"college_code": self.college_code}
        out["run_id"] = str(self.run_id) if self.run_id else ""
        out["task_id"] = self.task_id or ""
        out["phase"] = self.phase.value if self.phase is not None else ""
        out["event_code"] = self.event_code or ""
        return out


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
