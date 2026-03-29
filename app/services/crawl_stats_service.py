"""크롤 통계 조회 서비스. Repository 결과(CrawlRunRow)를 도메인 결과(CrawlStatsResult)로 변환."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import IngestionAttemptStatus
from app.domain.contracts.crawl_contracts import (
    CrawlRunItem,
    CrawlSourceFreshnessItem,
    CrawlStatsQueryPort,
    CrawlStatsResult,
)


class CrawlStatsService:
    """크롤 통계 조회. CrawlStatsQueryPort를 주입받아 Repository와 분리."""

    def __init__(self, query_port: CrawlStatsQueryPort) -> None:
        self._query_port = query_port

    async def get_crawl_stats(self, session: AsyncSession, limit: int = 50) -> CrawlStatsResult:
        """
        최근 크롤 실행 이력. Port에서 CrawlRunRow 목록 조회 후
        error_message는 제거하고 has_error로만 노출해 CrawlStatsResult 반환.
        캐시·스키마 변환은 호출자(라우터)에서 처리.
        """
        rows = await self._query_port.fetch_recent(session, limit)
        items = [
            CrawlRunItem(
                college_code=row.college_code,
                started_at=row.started_at.isoformat() if row.started_at else None,
                finished_at=row.finished_at.isoformat() if row.finished_at else None,
                status=row.status,
                notices_upserted=row.notices_upserted,
                has_error=bool(row.error_message),
            )
            for row in rows
        ]
        fresh_rows = await self._query_port.fetch_source_freshness(session)

        def _utc(dt: datetime) -> datetime:
            if dt.tzinfo is None:
                return dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)

        now = datetime.now(UTC)
        stale_after = timedelta(seconds=settings.crawl_freshness_stale_seconds)
        crawl_stale_after = timedelta(seconds=settings.crawl_run_stale_seconds)
        freshness: list[CrawlSourceFreshnessItem] = []
        for fr in fresh_rows:
            is_stale = True
            if fr.last_attempt_status is None:
                is_stale = True
            elif fr.last_attempt_status == IngestionAttemptStatus.RUNNING.value:
                if fr.last_attempt_started_at is not None:
                    is_stale = now - _utc(fr.last_attempt_started_at) > crawl_stale_after
                else:
                    is_stale = True
            elif fr.last_attempt_status == IngestionAttemptStatus.SUCCESS.value and fr.last_attempt_finished_at:
                fin = _utc(fr.last_attempt_finished_at)
                is_stale = now - fin > stale_after
            elif fr.last_attempt_finished_at is not None:
                fin = _utc(fr.last_attempt_finished_at)
                is_stale = now - fin > stale_after
            freshness.append(
                CrawlSourceFreshnessItem(
                    college_code=fr.college_code,
                    last_attempt_status=fr.last_attempt_status,
                    last_attempt_started_at=(
                        fr.last_attempt_started_at.isoformat() if fr.last_attempt_started_at else None
                    ),
                    last_attempt_finished_at=(
                        fr.last_attempt_finished_at.isoformat() if fr.last_attempt_finished_at else None
                    ),
                    total_docs=fr.total_docs,
                    is_stale=is_stale,
                )
            )
        return CrawlStatsResult(runs=items, limit=limit, source_freshness=freshness)
