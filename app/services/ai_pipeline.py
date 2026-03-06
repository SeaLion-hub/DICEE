"""
AI 파이프라인 서비스 (4단계).

NoticeAIExtraction 스키마를 DB 투영·Instructor 연동 전담.
설계: docs/decisions/ai-extraction-schema.md, ROADMAP_PHASES 4단계.
"""

from __future__ import annotations

from typing import Any

from app.schemas.ai import NoticeAIExtraction


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
