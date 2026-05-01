"""내부 API 전용 응답 스키마. error_message 등 민감 필드는 노출하지 않음."""

from pydantic import Field

from app.schemas.base import BaseSchema


class CrawlRunStatsItem(BaseSchema):
    """GET /internal/crawl-stats 응답의 run 한 건. error_message는 has_error로만 노출."""

    college_code: str
    started_at: str | None
    finished_at: str | None
    status: str
    notices_upserted: int
    has_error: bool


class CrawlSourceFreshnessStatsItem(BaseSchema):
    """primary 소스별 마지막 ingestion 시도 요약 (운영 대시보드)."""

    college_code: str
    last_attempt_status: str | None
    last_attempt_started_at: str | None
    last_attempt_finished_at: str | None
    total_docs: int | None
    is_stale: bool


class CrawlStatsResponse(BaseSchema):
    """GET /internal/crawl-stats 응답 body."""

    runs: list[CrawlRunStatsItem]
    limit: int
    source_freshness: list[CrawlSourceFreshnessStatsItem] = Field(default_factory=list)


class AiAdminTokenUsage(BaseSchema):
    """AI 관리자 토큰 usage 요약."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class AiAdminCostEstimate(BaseSchema):
    """AI 관리자 추정 비용. 실제 과금액이 아닌 설정 단가 기반 estimated 값."""

    estimated: bool = True
    currency: str = "USD"
    input_usd_per_1m: float | None = None
    output_usd_per_1m: float | None = None
    prompt_usd: float | None = None
    completion_usd: float | None = None
    total_usd: float | None = None
    reason: str | None = None


class AiAdminTestResult(BaseSchema):
    """공지 1건 AI 드라이런/반영 결과."""

    notice_id: str
    title: str
    college_name: str
    college_code: str
    mode: str
    status: str
    html_source: str
    remote_fetch_disabled: bool
    image_count_requested: int
    usage: AiAdminTokenUsage
    cost: AiAdminCostEstimate
    meta: dict = Field(default_factory=dict)
    summary: dict = Field(default_factory=dict)
    result: dict = Field(default_factory=dict)
    envelope: dict = Field(default_factory=dict)
    source_quality: str
    usage_quality: str
    cost_quality: str
    token_band: str
    admin_advice: str
    updated_rows: int = 0


class AiAdminUsageSummary(BaseSchema):
    """토큰 대시보드 기간별 요약."""

    label: str
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    call_count: int
    average_total_tokens: float
    estimated_cost_usd: float | None
    valid_usage_count: int
    missing_usage_count: int
    invalid_usage_count: int
    unavailable_usage_count: int


class AiAdminUsageDashboard(BaseSchema):
    """로컬 AI 토큰/비용 대시보드 JSON."""

    generated_at: str
    period_days: int
    max_rows: int
    scanned_rows: int
    source_definition: str
    overall: AiAdminUsageSummary
    last_24h: AiAdminUsageSummary
    last_7d: AiAdminUsageSummary
    buckets: dict[str, int]
    by_model: list[dict] = Field(default_factory=list)
    by_college: list[dict] = Field(default_factory=list)
    top_notices: list[dict] = Field(default_factory=list)
