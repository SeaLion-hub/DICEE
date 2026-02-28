"""내부 API 전용 응답 스키마. error_message 등 민감 필드는 노출하지 않음."""

from pydantic import BaseModel


class CrawlRunStatsItem(BaseModel):
    """GET /internal/crawl-stats 응답의 run 한 건. error_message는 has_error로만 노출."""

    college_code: str
    started_at: str | None
    finished_at: str | None
    status: str
    notices_upserted: int
    has_error: bool


class CrawlStatsResponse(BaseModel):
    """GET /internal/crawl-stats 응답 body."""

    runs: list[CrawlRunStatsItem]
    limit: int
