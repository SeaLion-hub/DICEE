"""
AI 파이프라인 서비스 (4단계).

NoticeAIExtraction 스키마를 DB 투영·추출기 호출·폴백 전담.
실제 LLM 프롬프트·호출은 app.services.ai.extractor.
설계: docs/decisions/ai-extraction-schema.md, ROADMAP_PHASES 4단계.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from app.domain.contracts.ai_extraction import NoticeAIExtraction
from app.services.ai.extractor import extract_notice_structured

logger = logging.getLogger(__name__)

EXTRACTION_MAX_RETRIES = 3


def extract_notice_info(html_content: str) -> NoticeAIExtraction:
    """
    HTML 공지 본문에서 NoticeAIExtraction 구조화 추출.
    extract_notice_structured 호출, 검증 실패 시 최대 EXTRACTION_MAX_RETRIES 재시도 후 폴백 반환.
    """
    last_error: Exception | None = None
    for _ in range(EXTRACTION_MAX_RETRIES + 1):
        try:
            return extract_notice_structured(html_content)
        except (ValidationError, Exception) as e:  # noqa: BLE001
            last_error = e
            try:
                from instructor.core.exceptions import InstructorRetryException
                if isinstance(e, InstructorRetryException):
                    continue
            except ImportError:
                pass
            if isinstance(e, ValidationError):
                continue
            raise
    try:
        from instructor.core.exceptions import InstructorRetryException
    except ImportError:
        InstructorRetryException = type("InstructorRetryException", (Exception,), {})

    e = last_error
    if e is not None and isinstance(e, (InstructorRetryException, ValidationError)):
        logger.warning(
            "AI extraction validation failed after retries; using fallback. error=%s",
            type(e).__name__,
            exc_info=True,
        )
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except Exception:  # noqa: S110
            pass
        return NoticeAIExtraction()
    if e is not None:
        raise e
    return NoticeAIExtraction()


def project_extraction_to_notice_fields(extraction: NoticeAIExtraction) -> dict[str, Any]:
    """
    NoticeAIExtraction → Notice 테이블 업데이트용 dict.

    - ai_extracted_json: 전체 추출 결과 (JSON 직렬화 가능)
    - dates: schedules를 list[dict]로 (Notice.dates)
    - eligibility: eligibility_rules
    - hashtags: hashtags
    - category / sub_category: AI 대분류·소분류 (DB notices 컬럼에 투영)
    """
    raw = extraction.model_dump(mode="json")
    dates = [s.model_dump(mode="json") for s in extraction.schedules]
    return {
        "ai_extracted_json": raw,
        "dates": dates,
        "eligibility": extraction.eligibility_rules,
        "hashtags": extraction.hashtags,
        "category": extraction.category.value,
        "sub_category": extraction.sub_category,
    }
