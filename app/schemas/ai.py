"""
AI 추출 스키마 (4·5·6단계 공통).

API/응답 레이어용 re-export. 정의는 app.domain.contracts.ai_extraction 에 있음.
Instructor response_model 및 DB ai_extracted_json / Notice 투영 필드용.
설계: docs/decisions/ai-extraction-schema.md
"""

from __future__ import annotations

from app.domain.contracts.ai_extraction import (
    NoticeAIExtraction,
    NoticeCategory,
    ScheduleItem,
    ScheduleKind,
    TargetGrade,
)

__all__ = [
    "NoticeAIExtraction",
    "NoticeCategory",
    "ScheduleItem",
    "ScheduleKind",
    "TargetGrade",
]
