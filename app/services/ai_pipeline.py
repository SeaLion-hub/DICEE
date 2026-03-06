"""
AI 파이프라인 서비스 (4단계).

NoticeAIExtraction 스키마를 DB 투영·Instructor 연동 전담.
설계: docs/decisions/ai-extraction-schema.md, ROADMAP_PHASES 4단계.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from app.core.config import settings
from app.domain.contracts.ai_extraction import NoticeAIExtraction, NoticeCategory

logger = logging.getLogger(__name__)

EXTRACTION_MAX_RETRIES = 3
_SYSTEM_PROMPT = """당신은 대학 공지 HTML에서 구조화된 정보를 추출하는 도우미입니다.
주어진 HTML에서 다음을 추출하세요:
- notice_category: 공지 유형(모집/안내/행사 등)
- summary: 공지 요약(선택)
- schedules: 일정 목록(마감일, 면접일 등). 날짜는 한국(KST) 기준으로 해석하고, 파싱 불가 시 date_raw에 원문만 넣으세요.
- raw_eligibility_text: 지원 자격 관련 문장을 가공 없이 발췌. 없으면 null.
- eligibility_rules: 위 원문을 바탕으로 분절한 자격 조건 리스트
- target_departments: 자격에 명시된 학과 리스트. 없으면 빈 리스트. "없음","알 수 없음" 등 플레이스홀더는 사용하지 마세요.
- target_grades: 자격에 명시된 학년(1~6, all). 없으면 빈 리스트.
- hashtags: 검색/필터용 해시태그
target_departments에 "없음", "알 수 없음", "해당없음" 등을 넣지 말고, 해당 없으면 빈 리스트를 반환하세요."""


def _get_instructor_client():  # noqa: ANN202
    import instructor

    api_key = None
    if settings.gemini_api_key:
        api_key = settings.gemini_api_key.get_secret_value()
    provider = f"google/{settings.gemini_model}"
    if api_key:
        return instructor.from_provider(provider, api_key=api_key, max_retries=0)
    return instructor.from_provider(provider, max_retries=0)


def extract_notice_info(html_content: str) -> NoticeAIExtraction:
    """
    HTML 공지 본문에서 NoticeAIExtraction 구조화 추출.
    Instructor + Gemini 사용, 검증 실패 시 max_retries 만큼 재시도 후 실패하면 Fallback 반환.
    """
    try:
        client = _get_instructor_client()
        response = client.create(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": html_content[:100_000] or "(내용 없음)"},
            ],
            response_model=NoticeAIExtraction,
            max_retries=EXTRACTION_MAX_RETRIES,
        )
        return response
    except Exception as e:  # noqa: BLE001
        try:
            from instructor.core.exceptions import InstructorRetryException
        except ImportError:
            InstructorRetryException = type("InstructorRetryException", (Exception,), {})

        if isinstance(e, (InstructorRetryException, ValidationError)):
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
            return NoticeAIExtraction(notice_category=NoticeCategory.OTHER)
        raise


def project_extraction_to_notice_fields(extraction: NoticeAIExtraction) -> dict[str, Any]:
    """
    NoticeAIExtraction → Notice 테이블 업데이트용 dict.

    - ai_extracted_json: 전체 추출 결과 (JSON 직렬화 가능)
    - dates: schedules를 list[dict]로 (Notice.dates)
    - eligibility: eligibility_rules
    - hashtags: hashtags
    - category: notice_category.value (notices.category)
    """
    raw = extraction.model_dump(mode="json")
    dates = [s.model_dump(mode="json") for s in extraction.schedules]
    return {
        "ai_extracted_json": raw,
        "dates": dates,
        "eligibility": extraction.eligibility_rules,
        "hashtags": extraction.hashtags,
        "category": extraction.notice_category.value,
    }
