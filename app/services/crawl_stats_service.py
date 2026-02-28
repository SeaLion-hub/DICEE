"""크롤 통계 조회 서비스. Repository 결과(CrawlRunRow)를 API 스키마(CrawlStatsResponse)로 변환."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.contracts.crawl_contracts import CrawlStatsQueryPort
from app.schemas.internal import CrawlRunStatsItem, CrawlStatsResponse


class CrawlStatsService:
    """크롤 통계 조회. CrawlStatsQueryPort를 주입받아 Repository와 분리."""

    def __init__(self, query_port: CrawlStatsQueryPort) -> None:
        self._query_port = query_port

    async def get_crawl_stats(self, session: AsyncSession, limit: int = 50) -> CrawlStatsResponse:
        """
        최근 크롤 실행 이력. Port에서 CrawlRunRow 목록 조회 후
        error_message는 제거하고 has_error로만 노출해 CrawlStatsResponse 반환.
        캐시는 호출자(라우터)에서 처리.
        """
        rows = await self._query_port.fetch_recent(session, limit)
        items = [
            CrawlRunStatsItem(
                college_code=row.college_code,
                started_at=row.started_at.isoformat() if row.started_at else None,
                finished_at=row.finished_at.isoformat() if row.finished_at else None,
                status=row.status,
                notices_upserted=row.notices_upserted,
                has_error=bool(row.error_message),
            )
            for row in rows
        ]
        return CrawlStatsResponse(runs=items, limit=limit)
