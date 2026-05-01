"""Local-only AI admin helpers for one-notice dry-runs, apply, and usage stats."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from redis.asyncio import Redis as RedisAsyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis import (
    LUA_RELEASE_IF_OWNER,
    clear_trigger_idempotency_in_progress,
    get_trigger_idempotency_result,
    set_trigger_idempotency_result,
    try_claim_trigger_idempotency,
)
from app.core.url_safety import is_safe_worker_http_url
from app.domain.contracts.ai_extraction import NoticeAIExtraction
from app.repositories.notice_repository import (
    AdminAiUsageSourceRow,
    AdminNoticeOptionRow,
    get_notice_for_ai_admin,
    list_ai_usage_source_rows_for_admin,
    list_recent_notices_for_ai_admin,
    update_ai_result_admin,
)
from app.repositories.notice_schedule_repository import replace_notice_schedules
from app.services.ai.exceptions import AIProviderRetryableError
from app.services.ai_pipeline import ExtractionEnvelope, extract_notice_info, project_extraction_to_notice_fields

logger = logging.getLogger(__name__)

ADMIN_APPLY_LOCK_PREFIX = "dicee:admin_ai_apply_lock:"
MAX_IMAGES_FOR_ADMIN_AI = 5
DEFAULT_MODEL_COSTS_USD_PER_MILLION: dict[str, tuple[float, float]] = {
    # Gemini API public paid-tier token prices. Override with AI_ADMIN_MODEL_COSTS_USD_PER_MILLION if pricing changes.
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-flash-latest": (0.075, 0.30),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.0-flash-001": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
}


class AiAdminError(Exception):
    """Base error for local AI admin service."""


class AiAdminNotFoundError(AiAdminError):
    """Requested notice does not exist or is deleted."""


class AiAdminConflictError(AiAdminError):
    """A duplicate or concurrent admin operation is already in progress."""


class AiAdminDependencyUnavailableError(AiAdminError):
    """Required dependency, such as Redis for apply safety, is unavailable."""


class AiAdminValidationError(AiAdminError):
    """Invalid admin request."""


@dataclass(frozen=True)
class AdminCostEstimate:
    estimated: bool
    currency: str
    input_usd_per_1m: float | None
    output_usd_per_1m: float | None
    prompt_usd: float | None
    completion_usd: float | None
    total_usd: float | None
    reason: str | None = None


@dataclass(frozen=True)
class AdminTokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class AdminNoticeOption:
    id: str
    title: str
    college_name: str
    college_code: str
    published_at: str | None
    ai_status: str
    total_tokens: int | None


@dataclass(frozen=True)
class AdminAiTestResult:
    notice_id: str
    title: str
    college_name: str
    college_code: str
    mode: str
    status: str
    html_source: str
    remote_fetch_disabled: bool
    image_count_requested: int
    usage: AdminTokenUsage
    cost: AdminCostEstimate
    meta: dict[str, Any]
    summary: dict[str, Any]
    result: dict[str, Any]
    envelope: dict[str, Any]
    source_quality: str
    usage_quality: str
    cost_quality: str
    token_band: str
    admin_advice: str
    updated_rows: int = 0


@dataclass(frozen=True)
class AdminApplyClaim:
    notice_id: uuid.UUID
    idempotency_key: str
    scope: str
    lock_token: str


@dataclass(frozen=True)
class AdminTopUsageNotice:
    notice_id: str
    title: str
    college_code: str
    model: str
    total_tokens: int
    estimated_cost_usd: float | None
    updated_at: str | None


@dataclass(frozen=True)
class AdminUsageSummary:
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


@dataclass(frozen=True)
class AdminUsageDashboard:
    generated_at: str
    period_days: int
    max_rows: int
    scanned_rows: int
    source_definition: str
    overall: AdminUsageSummary
    last_24h: AdminUsageSummary
    last_7d: AdminUsageSummary
    buckets: dict[str, int]
    by_model: list[dict[str, Any]]
    by_college: list[dict[str, Any]]
    top_notices: list[AdminTopUsageNotice]


@dataclass(frozen=True)
class _HtmlInput:
    html: str
    source: str
    remote_fetch_disabled: bool


@dataclass(frozen=True)
class _UsageRecord:
    row: AdminAiUsageSourceRow
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: AdminCostEstimate
    valid: bool
    missing: bool
    unavailable: bool


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(UTC).replace(microsecond=0).isoformat()


def _plain_dataclass(value: Any) -> dict[str, Any]:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    return {}


def _notice_option_from_row(row: AdminNoticeOptionRow) -> AdminNoticeOption:
    return AdminNoticeOption(
        id=str(row.id),
        title=row.title,
        college_name=row.college_name,
        college_code=row.college_code,
        published_at=_iso(row.published_at),
        ai_status=row.ai_status,
        total_tokens=row.total_tokens,
    )


def _parse_uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise AiAdminValidationError("notice_id must be a valid UUID") from exc


def _read_local_notice_html(content_url: str | None, title: str) -> _HtmlInput:
    url = (content_url or "").strip()
    if not url:
        return _HtmlInput(
            html=f"<title>{title}</title>" if title else "",
            source="title_fallback",
            remote_fetch_disabled=False,
        )
    if url.startswith(("http://", "https://")):
        return _HtmlInput(
            html=f"<title>{title}</title>" if title else "",
            source="remote_fetch_disabled",
            remote_fetch_disabled=True,
        )

    key = url.lstrip("/")
    base = Path(settings.content_storage_local_path or "storage/contents").resolve()
    path = (base / key).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        return _HtmlInput(
            html=f"<title>{title}</title>" if title else "",
            source="path_blocked",
            remote_fetch_disabled=False,
        )
    if not path.is_file():
        return _HtmlInput(
            html=f"<title>{title}</title>" if title else "",
            source="title_fallback",
            remote_fetch_disabled=False,
        )
    return _HtmlInput(html=path.read_text(encoding="utf-8"), source="local_content_url", remote_fetch_disabled=False)


def _image_urls_from_json_list(images: object, *, include_vision: bool) -> list[str]:
    if not include_vision or not images or not isinstance(images, list):
        return []
    urls: list[str] = []
    for item in images[:MAX_IMAGES_FOR_ADMIN_AI]:
        if not isinstance(item, dict):
            continue
        raw = item.get("url") or item.get("src") or ""
        url = str(raw).strip()
        if url and is_safe_worker_http_url(url):
            urls.append(url)
    return urls


def _model_cost_table() -> dict[str, tuple[float, float]]:
    table: dict[str, tuple[float, float]] = dict(DEFAULT_MODEL_COSTS_USD_PER_MILLION)
    raw = (settings.ai_admin_model_costs_usd_per_million or "").strip()
    if not raw:
        return table
    for item in raw.split(","):
        parts = [p.strip() for p in item.split(":")]
        if len(parts) != 3 or not parts[0]:
            continue
        try:
            table[parts[0]] = (float(parts[1]), float(parts[2]))
        except ValueError:
            continue
    return table


def estimate_cost(model: str, usage: AdminTokenUsage) -> AdminCostEstimate:
    table = _model_cost_table()
    normalized_model = model.removeprefix("google/").strip()
    prices = table.get(normalized_model)
    if prices is None:
        return AdminCostEstimate(
            estimated=True,
            currency="USD",
            input_usd_per_1m=None,
            output_usd_per_1m=None,
            prompt_usd=None,
            completion_usd=None,
            total_usd=None,
            reason="unknown_model_cost",
        )
    input_price, output_price = prices
    prompt_usd = usage.prompt_tokens / 1_000_000 * input_price
    completion_usd = usage.completion_tokens / 1_000_000 * output_price
    return AdminCostEstimate(
        estimated=True,
        currency="USD",
        input_usd_per_1m=input_price,
        output_usd_per_1m=output_price,
        prompt_usd=prompt_usd,
        completion_usd=completion_usd,
        total_usd=prompt_usd + completion_usd,
    )


def _usage_unavailable_cost(model: str) -> AdminCostEstimate:
    table = _model_cost_table()
    normalized_model = model.removeprefix("google/").strip()
    prices = table.get(normalized_model)
    input_price = output_price = None
    if prices is not None:
        input_price, output_price = prices
    return AdminCostEstimate(
        estimated=False,
        currency="USD",
        input_usd_per_1m=input_price,
        output_usd_per_1m=output_price,
        prompt_usd=None,
        completion_usd=None,
        total_usd=None,
        reason="usage_unavailable",
    )


def _usage_is_unavailable_after_llm_call(meta: dict[str, Any], usage: AdminTokenUsage) -> bool:
    try:
        llm_calls = int(meta.get("llm_call_count") or 0)
    except (TypeError, ValueError):
        llm_calls = 0
    return llm_calls > 0 and usage.prompt_tokens == 0 and usage.completion_tokens == 0 and usage.total_tokens == 0


def _source_quality(html_source: str) -> str:
    if html_source == "local_content_url":
        return "ok"
    if html_source == "path_blocked":
        return "blocked"
    return "warning"


def _usage_quality(meta: dict[str, Any], usage: AdminTokenUsage) -> str:
    if _usage_is_unavailable_after_llm_call(meta, usage):
        return "unavailable"
    if usage.prompt_tokens < 0 or usage.completion_tokens < 0 or usage.total_tokens < 0:
        return "invalid"
    return "valid"


def _cost_quality(cost: AdminCostEstimate) -> str:
    if cost.reason == "usage_unavailable":
        return "usage_unavailable"
    if cost.reason == "unknown_model_cost":
        return "unknown_model_cost"
    return "estimated"


def _token_band(total_tokens: int) -> str:
    if total_tokens < 1000:
        return "0-1k"
    if total_tokens < 3000:
        return "1k-3k"
    if total_tokens < 10000:
        return "3k-10k"
    return "10k+"


def _admin_advice(
    *,
    html_source: str,
    source_quality: str,
    usage_quality: str,
    token_band: str,
    cost_quality: str,
) -> str:
    if source_quality == "blocked":
        return "본문 경로가 차단되어 실제 비용을 판단할 수 없습니다. content_url 저장 경로를 먼저 확인하세요."
    if html_source == "remote_fetch_disabled":
        return "원격 본문 fetch가 차단되어 제목만 측정했습니다. 실제 본문 처리 비용은 더 높을 수 있습니다."
    if html_source == "title_fallback":
        return "저장된 본문이 없어 제목만 측정했습니다. 비용과 추출 품질을 과소평가할 수 있습니다."
    if usage_quality == "unavailable":
        return (
            "AI 호출은 성공했지만 토큰 사용량을 받지 못했습니다. "
            "비용을 0으로 보지 말고 provider usage 응답을 확인하세요."
        )
    if usage_quality == "invalid":
        return "저장된 토큰 값이 유효하지 않습니다. 이 기록은 비용 집계에서 제외해야 합니다."
    if cost_quality == "unknown_model_cost":
        return "모델 가격표가 없어 비용을 계산하지 못했습니다. AI_ADMIN_MODEL_COSTS_USD_PER_MILLION을 설정하세요."
    if token_band == "10k+":
        return "토큰 사용량이 높은 공지입니다. 본문 정리나 이미지 사용 여부를 확인하세요."
    if token_band == "3k-10k":
        return "일반적인 범위의 토큰 사용량입니다. 현재 모델과 프롬프트로 관리 가능한 수준입니다."
    return "낮은 토큰 사용량입니다. 비용 관점에서는 부담이 작습니다."


def _usage_from_envelope(envelope: ExtractionEnvelope) -> AdminTokenUsage:
    return AdminTokenUsage(
        prompt_tokens=int(envelope.usage.prompt_tokens or 0),
        completion_tokens=int(envelope.usage.completion_tokens or 0),
        total_tokens=int(envelope.usage.total_tokens or 0),
    )


def _summary_from_extraction(extraction: NoticeAIExtraction) -> dict[str, Any]:
    return {
        "summary": extraction.summary,
        "main_categories": [c.value for c in extraction.main_categories],
        "sub_categories": [sub for mapping in extraction.taxonomy_mappings for sub in mapping.sub_categories if sub],
        "schedules": [s.model_dump(mode="json") for s in extraction.schedules],
        "eligibility_rules": list(extraction.eligibility_rules),
        "target_departments": list(extraction.target_departments),
    }


def _build_test_result(
    *,
    notice: object,
    mode: str,
    html_input: _HtmlInput,
    image_urls: list[str],
    envelope: ExtractionEnvelope,
    updated_rows: int = 0,
) -> AdminAiTestResult:
    meta = _plain_dataclass(envelope.meta)
    usage = _usage_from_envelope(envelope)
    model = str(meta.get("model") or "")
    result = envelope.result.model_dump(mode="json")
    envelope_dict = {
        "status": envelope.status,
        "usage": asdict(usage),
        "meta": meta,
        "result": result,
    }
    college = getattr(notice, "college", None)
    cost = (
        _usage_unavailable_cost(model)
        if _usage_is_unavailable_after_llm_call(meta, usage)
        else estimate_cost(model, usage)
    )
    source_quality = _source_quality(html_input.source)
    usage_quality = _usage_quality(meta, usage)
    cost_quality = _cost_quality(cost)
    token_band = _token_band(usage.total_tokens)
    return AdminAiTestResult(
        notice_id=str(notice.id),
        title=str(getattr(notice, "title", "") or ""),
        college_name=str(getattr(college, "name", "") or ""),
        college_code=str(getattr(college, "external_id", "") or ""),
        mode=mode,
        status=envelope.status,
        html_source=html_input.source,
        remote_fetch_disabled=html_input.remote_fetch_disabled,
        image_count_requested=len(image_urls),
        usage=usage,
        cost=cost,
        meta=meta,
        summary=_summary_from_extraction(envelope.result),
        result=result,
        envelope=envelope_dict,
        source_quality=source_quality,
        usage_quality=usage_quality,
        cost_quality=cost_quality,
        token_band=token_band,
        admin_advice=_admin_advice(
            html_source=html_input.source,
            source_quality=source_quality,
            usage_quality=usage_quality,
            token_band=token_band,
            cost_quality=cost_quality,
        ),
        updated_rows=updated_rows,
    )


async def _extract_notice_info_for_admin(
    html: str,
    image_urls: list[str],
    title: str,
    college_name: str,
) -> ExtractionEnvelope:
    try:
        return await asyncio.to_thread(
            extract_notice_info,
            html,
            image_urls,
            title,
            college_name,
        )
    except AIProviderRetryableError as exc:
        raise AiAdminDependencyUnavailableError(
            "AI provider quota/rate limit exceeded. Check Gemini billing/quota or set GEMINI_MODEL to a model with "
            "available quota."
        ) from exc


class AiAdminService:
    """Business logic for local AI admin pages."""

    async def list_notice_options(self, session: AsyncSession, *, limit: int) -> list[AdminNoticeOption]:
        rows = await list_recent_notices_for_ai_admin(session, limit=limit)
        return [_notice_option_from_row(row) for row in rows]

    async def run_dry_run(
        self,
        session: AsyncSession,
        *,
        notice_id: str,
        include_vision: bool,
    ) -> AdminAiTestResult:
        notice_uuid = _parse_uuid(notice_id)
        notice = await get_notice_for_ai_admin(session, notice_uuid)
        if notice is None:
            raise AiAdminNotFoundError("Notice not found")
        html_input = _read_local_notice_html(
            getattr(getattr(notice, "notice_content", None), "content_url", None),
            notice.title,
        )
        image_urls = _image_urls_from_json_list(notice.images, include_vision=include_vision)
        envelope = await _extract_notice_info_for_admin(
            html_input.html,
            image_urls,
            notice.title,
            notice.college.name if notice.college is not None else "",
        )
        return _build_test_result(
            notice=notice,
            mode="dry_run",
            html_input=html_input,
            image_urls=image_urls,
            envelope=envelope,
        )

    async def prepare_apply_claim(
        self,
        redis_client: RedisAsyncio | None,
        *,
        notice_id: str,
        idempotency_key: str,
    ) -> tuple[AdminApplyClaim | None, dict[str, Any] | None]:
        if redis_client is None:
            raise AiAdminDependencyUnavailableError("Redis is required for admin apply safety")
        notice_uuid = _parse_uuid(notice_id)
        idem = (idempotency_key or "").strip()
        if not idem:
            raise AiAdminValidationError("Idempotency-Key header is required")
        scope = f"ai_admin_apply:{notice_uuid}"
        cached = await get_trigger_idempotency_result(redis_client, idem, scope)
        if cached is not None:
            return None, cached
        claimed = await try_claim_trigger_idempotency(redis_client, idem, scope, fail_closed=True)
        if not claimed:
            raise AiAdminConflictError("Admin apply idempotency key is already in progress")
        token = str(uuid.uuid4())
        lock_key = f"{ADMIN_APPLY_LOCK_PREFIX}{notice_uuid}"
        try:
            ok = await redis_client.set(lock_key, token, nx=True, ex=settings.ai_admin_apply_lock_ttl_seconds)
        except Exception as exc:
            await clear_trigger_idempotency_in_progress(redis_client, idem, scope)
            raise AiAdminDependencyUnavailableError("Admin apply lock unavailable") from exc
        if not ok:
            await clear_trigger_idempotency_in_progress(redis_client, idem, scope)
            raise AiAdminConflictError("Another admin apply is already running for this notice")
        return AdminApplyClaim(notice_id=notice_uuid, idempotency_key=idem, scope=scope, lock_token=token), None

    async def run_apply(
        self,
        session: AsyncSession,
        *,
        claim: AdminApplyClaim,
        include_vision: bool,
        confirmation: str,
    ) -> AdminAiTestResult:
        notice = await get_notice_for_ai_admin(session, claim.notice_id)
        if notice is None:
            raise AiAdminNotFoundError("Notice not found")
        expected = str(claim.notice_id)
        title = str(notice.title or "")
        conf = (confirmation or "").strip()
        if conf != expected and (not title or conf not in title):
            raise AiAdminValidationError("Confirmation must match the notice id or part of the notice title")

        html_input = _read_local_notice_html(
            getattr(getattr(notice, "notice_content", None), "content_url", None),
            notice.title,
        )
        image_urls = _image_urls_from_json_list(notice.images, include_vision=include_vision)
        envelope = await _extract_notice_info_for_admin(
            html_input.html,
            image_urls,
            notice.title,
            notice.college.name if notice.college is not None else "",
        )
        meta = {
            **_plain_dataclass(envelope.meta),
            "usage": _plain_dataclass(envelope.usage),
            "admin_run": True,
            "admin_mode": "apply",
            "html_source": html_input.source,
            "remote_fetch_disabled": html_input.remote_fetch_disabled,
        }
        projected = project_extraction_to_notice_fields(envelope.result, envelope_meta=meta)
        rows = await update_ai_result_admin(
            session,
            claim.notice_id,
            projected["ai_extracted_json"],
            dates=projected["dates"],
            eligibility=projected["eligibility"],
            hashtags=projected["hashtags"],
            taxonomy_rows=projected["taxonomy_rows"],
        )
        if rows != 1:
            raise AiAdminConflictError("Admin apply updated no rows")
        await replace_notice_schedules(session, claim.notice_id, envelope.result.schedules)
        return _build_test_result(
            notice=notice,
            mode="apply",
            html_input=html_input,
            image_urls=image_urls,
            envelope=envelope,
            updated_rows=rows,
        )

    async def complete_apply(
        self,
        redis_client: RedisAsyncio | None,
        claim: AdminApplyClaim,
        payload: dict[str, Any],
    ) -> None:
        if redis_client is None:
            return
        await set_trigger_idempotency_result(redis_client, claim.idempotency_key, claim.scope, payload)
        await self.release_apply_claim(redis_client, claim)

    async def abort_apply(self, redis_client: RedisAsyncio | None, claim: AdminApplyClaim | None) -> None:
        if redis_client is None or claim is None:
            return
        await clear_trigger_idempotency_in_progress(redis_client, claim.idempotency_key, claim.scope)
        await self.release_apply_claim(redis_client, claim)

    async def release_apply_claim(self, redis_client: RedisAsyncio | None, claim: AdminApplyClaim) -> None:
        if redis_client is None:
            return
        lock_key = f"{ADMIN_APPLY_LOCK_PREFIX}{claim.notice_id}"
        try:
            await redis_client.eval(LUA_RELEASE_IF_OWNER, 1, lock_key, claim.lock_token)
        except Exception:
            logger.warning("Admin AI apply lock release failed.", exc_info=True)

    async def usage_dashboard(
        self,
        session: AsyncSession,
        *,
        period_days: int,
        limit: int | None = None,
    ) -> AdminUsageDashboard:
        now = datetime.now(UTC)
        bounded_days = max(1, min(period_days, 365))
        max_rows = int(limit or settings.ai_admin_dashboard_max_rows)
        since = now - timedelta(days=bounded_days)
        rows = await list_ai_usage_source_rows_for_admin(session, since=since, limit=max_rows)
        records = [_usage_record_from_row(row) for row in rows]
        return _build_dashboard(now=now, period_days=bounded_days, max_rows=max_rows, records=records)


def result_to_payload(result: AdminAiTestResult) -> dict[str, Any]:
    """Pydantic-free conversion for idempotency cache and JSON responses."""
    return asdict(result)


def _usage_record_from_row(row: AdminAiUsageSourceRow) -> _UsageRecord:
    usage_raw: Any = None
    model = "unknown"
    envelope_meta: dict[str, Any] = {}
    missing = False
    valid = False
    unavailable = False
    if isinstance(row.ai_extracted_json, dict):
        metadata = row.ai_extracted_json.get("metadata")
        if isinstance(metadata, dict):
            raw_envelope_meta = metadata.get("_envelope_meta")
            if isinstance(raw_envelope_meta, dict):
                envelope_meta = raw_envelope_meta
                model = str(envelope_meta.get("model") or "unknown")
                usage_raw = envelope_meta.get("usage")
    if usage_raw is None:
        missing = True
    prompt = completion = total = 0
    if isinstance(usage_raw, dict):
        try:
            prompt = int(usage_raw.get("prompt_tokens") or 0)
            completion = int(usage_raw.get("completion_tokens") or 0)
            total = int(usage_raw.get("total_tokens") or prompt + completion)
            valid = total >= 0 and prompt >= 0 and completion >= 0
        except (TypeError, ValueError):
            valid = False
    usage = AdminTokenUsage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)
    if valid and _usage_is_unavailable_after_llm_call(envelope_meta, usage):
        valid = False
        unavailable = True
    return _UsageRecord(
        row=row,
        model=model,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cost=_usage_unavailable_cost(model) if unavailable else estimate_cost(model, usage),
        valid=valid,
        missing=missing,
        unavailable=unavailable,
    )


def _summary_for_records(label: str, records: list[_UsageRecord]) -> AdminUsageSummary:
    valid = [r for r in records if r.valid]
    prompt = sum(r.prompt_tokens for r in valid)
    completion = sum(r.completion_tokens for r in valid)
    total = sum(r.total_tokens for r in valid)
    costs = [r.cost.total_usd for r in valid if r.cost.total_usd is not None]
    return AdminUsageSummary(
        label=label,
        total_tokens=total,
        prompt_tokens=prompt,
        completion_tokens=completion,
        call_count=len(valid),
        average_total_tokens=(total / len(valid)) if valid else 0.0,
        estimated_cost_usd=sum(costs) if costs else None,
        valid_usage_count=len(valid),
        missing_usage_count=sum(1 for r in records if r.missing),
        invalid_usage_count=sum(1 for r in records if not r.missing and not r.unavailable and not r.valid),
        unavailable_usage_count=sum(1 for r in records if r.unavailable),
    )


def _aggregate_group(records: list[_UsageRecord], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[_UsageRecord]] = defaultdict(list)
    for record in records:
        if not record.valid:
            continue
        value = record.model if key == "model" else record.row.college_code
        groups[value or "unknown"].append(record)
    out: list[dict[str, Any]] = []
    for value, items in groups.items():
        summary = _summary_for_records(value, items)
        out.append(asdict(summary))
    out.sort(key=lambda item: int(item["total_tokens"]), reverse=True)
    return out


def _build_dashboard(
    *,
    now: datetime,
    period_days: int,
    max_rows: int,
    records: list[_UsageRecord],
) -> AdminUsageDashboard:
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)
    last_24h = [r for r in records if r.row.updated_at is not None and r.row.updated_at >= cutoff_24h]
    last_7d = [r for r in records if r.row.updated_at is not None and r.row.updated_at >= cutoff_7d]
    valid = [r for r in records if r.valid]
    buckets = {"0-1k": 0, "1k-3k": 0, "3k-10k": 0, "10k+": 0}
    for record in valid:
        total = record.total_tokens
        if total < 1000:
            buckets["0-1k"] += 1
        elif total < 3000:
            buckets["1k-3k"] += 1
        elif total < 10000:
            buckets["3k-10k"] += 1
        else:
            buckets["10k+"] += 1
    top = sorted(valid, key=lambda r: r.total_tokens, reverse=True)[:20]
    return AdminUsageDashboard(
        generated_at=_iso(now) or "",
        period_days=period_days,
        max_rows=max_rows,
        scanned_rows=len(records),
        source_definition="DB notices.ai_extracted_json.metadata._envelope_meta.usage latest saved result per notice",
        overall=_summary_for_records("overall", records),
        last_24h=_summary_for_records("last_24h", last_24h),
        last_7d=_summary_for_records("last_7d", last_7d),
        buckets=buckets,
        by_model=_aggregate_group(records, "model"),
        by_college=_aggregate_group(records, "college"),
        top_notices=[
            AdminTopUsageNotice(
                notice_id=str(item.row.id),
                title=item.row.title,
                college_code=item.row.college_code,
                model=item.model,
                total_tokens=item.total_tokens,
                estimated_cost_usd=item.cost.total_usd,
                updated_at=_iso(item.row.updated_at),
            )
            for item in top
        ],
    )


def payload_to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
