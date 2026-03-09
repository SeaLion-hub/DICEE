"""
AI 파이프라인 서비스 (4단계).

NoticeAIExtraction 스키마를 DB 투영·추출기 호출·폴백 전담.
실제 LLM 프롬프트·호출은 app.services.ai.extractor.
설계: docs/decisions/ai-extraction-schema.md, ROADMAP_PHASES 4단계.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from bs4 import BeautifulSoup
from pydantic import ValidationError

from app.core.config import settings
from app.core.metrics import (
    AI_EXTRACTION_ATTEMPT_TOTAL,
    AI_EXTRACTION_FALLBACK_TOTAL,
    AI_EXTRACTION_PROVIDER_ERROR_TOTAL,
    AI_EXTRACTION_SUCCESS_TOTAL,
    AI_EXTRACTION_TOKENS_TOTAL,
    AI_EXTRACTION_VALIDATION_ERROR_TOTAL,
    increment,
)
from app.domain.contracts.ai_extraction import NoticeAIExtraction
from app.services.ai.extractor import extract_notice_structured_with_usage

logger = logging.getLogger(__name__)


@dataclass
class ExtractionEnvelope:
    """
    AI 추출 결과 래퍼.

    - result: 비즈니스 payload(NoticeAIExtraction) — DB에 그대로 저장.
    - usage: 토큰 사용량 등 집계용 메타데이터.
    - meta: fallback_reason, provider, pipeline_version 등 운영 메타데이터.
    """

    status: Literal["ok", "fallback"] = "ok"
    result: NoticeAIExtraction = field(
        default_factory=lambda: NoticeAIExtraction(target_departments=[])
    )
    # usage는 항상 prompt_tokens, completion_tokens, total_tokens 키를 포함한다.
    usage: dict[str, int] = field(
        default_factory=lambda: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
    )
    # meta는 provider, model, fallback_reason, elapsed_ms, html_raw_len, html_clean_len, image_count를 포함한다.
    meta: dict[str, Any] = field(default_factory=dict)


def _clean_notice_html(html_content: str) -> str:
    """
    공지 HTML에서 본문 텍스트만 추출하고 길이를 제한해 토큰 사용량을 줄인다.

    - script/style/nav/footer/noscript 제거
    - img alt 텍스트는 본문에 포함해 포스터·첨부 이미지 정보가 손실되지 않도록 함
    - 공백/빈 줄 정리, 최종 텍스트를 12k자 수준으로 제한
    """
    if not html_content:
        return ""

    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "noscript"]):
        tag.decompose()

    for img in soup.find_all("img"):
        alt = (img.get("alt") or "").strip()
        if alt:
            img.insert_before(f"[이미지: {alt}]")

    body_text = soup.get_text("\n")
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    text = "\n".join(lines)
    return text[:12_000]


def validate_extraction_raw_substrings(
    extraction: NoticeAIExtraction,
    source_text: str,
) -> None:
    """
    raw_eligibility_text 및 schedule의 date_raw/start_date_raw/end_date_raw가
    source_text의 부분 문자열인지 검사한다. 원문 근거가 없으면 ValueError.
    """
    if extraction.raw_eligibility_text and extraction.raw_eligibility_text.strip():
        if extraction.raw_eligibility_text.strip() not in source_text:
            raise ValueError(
                "raw_eligibility_text must be a substring of the source notice text."
            )
    for item in extraction.schedules:
        for raw_val in (item.date_raw, item.start_date_raw, item.end_date_raw):
            if raw_val and raw_val.strip():
                if raw_val.strip() not in source_text:
                    raise ValueError(
                        "Schedule date_raw/start_date_raw/end_date_raw must be substrings of the source text."
                    )


def extract_notice_info(
    html_content: str,
    image_urls: list[str] | None = None,
) -> ExtractionEnvelope:
    """
    HTML 공지 본문(및 선택적 이미지 URL)에서 NoticeAIExtraction 구조화 추출.

    - HTML을 전처리해 불필요한 태그·푸터 등을 제거하고 길이를 제한한다.
    - Instructor 레이어(_get_instructor_client)에서 max_retries로 self-correction 수행.
    - 여기서는 별도 재시도를 수행하지 않고, ValidationError/InstructorRetryException을
      fallback Envelope로 변환한다.
    """
    started_at = time.monotonic()
    raw_html = html_content or ""
    html_raw_len = len(raw_html)
    cleaned_html = _clean_notice_html(raw_html)
    html_clean_len = len(cleaned_html)
    # 전처리 결과가 비어 있으면 raw_html로 폴백하고, 그렇지 않으면 항상 전처리 텍스트를 사용한다.
    prompt_html = cleaned_html or raw_html
    image_count = len(image_urls or [])
    provider = f"google/{settings.gemini_model}"
    model = settings.gemini_model
    increment(AI_EXTRACTION_ATTEMPT_TOTAL)
    try:
        extraction, usage = extract_notice_structured_with_usage(
            prompt_html, image_urls=image_urls
        )
        if getattr(settings, "ai_extraction_enforce_raw_substrings", False) and not (
            image_urls or []
        ):
            try:
                validate_extraction_raw_substrings(extraction, prompt_html)
            except ValueError:
                elapsed_ms = int((time.monotonic() - started_at) * 1000)
                fallback_result = NoticeAIExtraction(target_departments=[])
                increment(AI_EXTRACTION_FALLBACK_TOTAL)
                increment(AI_EXTRACTION_VALIDATION_ERROR_TOTAL)
                return ExtractionEnvelope(
                    status="fallback",
                    result=fallback_result,
                    meta={
                        "pipeline_version": fallback_result.pipeline_version,
                        "provider": provider,
                        "model": model,
                        "fallback_reason": "raw_substring_validation_failed",
                        "html_raw_len": html_raw_len,
                        "html_clean_len": html_clean_len,
                        "image_count": image_count,
                        "elapsed_ms": elapsed_ms,
                    },
                )
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        envelope = ExtractionEnvelope(
            status="ok",
            result=extraction,
            usage={
                "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                "total_tokens": int(usage.get("total_tokens", 0) or 0),
            },
            meta={
                "pipeline_version": extraction.pipeline_version,
                "provider": provider,
                "model": model,
                "fallback_reason": None,
                "html_raw_len": html_raw_len,
                "html_clean_len": html_clean_len,
                "image_count": image_count,
                "elapsed_ms": elapsed_ms,
            },
        )
        increment(AI_EXTRACTION_SUCCESS_TOTAL)
        total_tokens = envelope.usage.get("total_tokens", 0) or 0
        if total_tokens:
            increment(AI_EXTRACTION_TOKENS_TOTAL, value=total_tokens)
        logger.info(
            "ai_extraction_completed",
            extra={
                "status": envelope.status,
                "fallback_reason": envelope.meta.get("fallback_reason") or "",
                "html_raw_len": html_raw_len,
                "html_clean_len": html_clean_len,
            },
        )
        return envelope
    except Exception as e:  # noqa: BLE001
        try:
            from instructor.core.exceptions import InstructorRetryException  # pyright: ignore[reportMissingImports]
        except ImportError:
            InstructorRetryException = type("InstructorRetryException", (Exception,), {})

        fallback_reasons: dict[type[BaseException], str] = {
            ValidationError: "validation_error",
            InstructorRetryException: "validation_retry_exhausted",
        }

        reason = "provider_error"
        for exc_type, tag in fallback_reasons.items():
            if isinstance(e, exc_type):
                reason = tag
                break

        if isinstance(e, (ValidationError, InstructorRetryException)):
            logger.warning(
                "AI extraction failed with validation-related error; using fallback. reason=%s",
                reason,
                exc_info=True,
            )
            try:
                import sentry_sdk

                sentry_sdk.capture_exception(e)
            except Exception:  # noqa: S110
                pass
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            fallback_result = NoticeAIExtraction(target_departments=[])
            envelope = ExtractionEnvelope(
                status="fallback",
                result=fallback_result,
                meta={
                    "pipeline_version": fallback_result.pipeline_version,
                    "provider": provider,
                    "model": model,
                    "fallback_reason": reason,
                    "html_raw_len": html_raw_len,
                    "html_clean_len": html_clean_len,
                    "image_count": image_count,
                    "elapsed_ms": elapsed_ms,
                },
            )
            increment(AI_EXTRACTION_FALLBACK_TOTAL)
            increment(AI_EXTRACTION_VALIDATION_ERROR_TOTAL)
            logger.info(
                "ai_extraction_completed",
                extra={
                    "status": envelope.status,
                    "fallback_reason": envelope.meta.get("fallback_reason") or "",
                    "html_raw_len": html_raw_len,
                    "html_clean_len": html_clean_len,
                },
            )
            return envelope

        # 비검증 계열 에러는 Celery autoretry에 맡기기 위해 그대로 전파.
        increment(AI_EXTRACTION_PROVIDER_ERROR_TOTAL)
        logger.error("AI extraction failed with unexpected error.", exc_info=True)
        raise


def project_extraction_to_notice_fields(
    extraction: NoticeAIExtraction,
    envelope_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    NoticeAIExtraction → Notice 테이블 업데이트용 dict.

    - ai_extracted_json: 전체 추출 결과 (JSON 직렬화 가능)
    - dates: schedules를 list[dict]로 (Notice.dates)
    - eligibility: eligibility_rules
    - hashtags: hashtags
    - category / sub_category: AI 대분류·소분류 (DB notices 컬럼에 투영)
    """
    raw = extraction.model_dump(mode="json")
    if envelope_meta:
        # 메타데이터는 top-level이 아닌 NoticeAIExtraction.metadata 안에 네임스페이스로 저장해
        # extra="forbid" 스키마의 round-trip을 유지한다.
        metadata = raw.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        metadata["_envelope_meta"] = envelope_meta
        raw["metadata"] = metadata
    dates = [s.model_dump(mode="json") for s in extraction.schedules]
    return {
        "ai_extracted_json": raw,
        "dates": dates,
        "eligibility": extraction.eligibility_rules,
        "hashtags": extraction.hashtags,
        "category": extraction.category.value,
        "sub_category": extraction.sub_category,
    }
