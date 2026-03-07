"""
AI 공지 추출: Instructor + Gemini 1.5 Flash.

NoticeAIExtraction 구조화 출력. 비대칭 날짜 처리·제한 조건 기반 자격 추출 규칙 적용.
설계: docs/decisions/ai-extraction-schema.md, PDF 「대학 공지사항 데이터 추출 품질 평가」.
"""

from __future__ import annotations

from app.core.config import settings
from app.domain.contracts.ai_extraction import NoticeAIExtraction


EXTRACTOR_SYSTEM_PROMPT = """당신은 대학 공지 HTML에서 구조화된 정보를 추출하는 도우미입니다.
한국 대학 공지이므로 모든 날짜·시간은 **KST(Asia/Seoul)** 기준으로 해석하세요.

## 출력 필드 개요
- category: 공지 대분류. scholarship, employment, event, academic, admission, international, other 중 하나만. 분류 불가 시 other.
- sub_category: 대분류 하위 라벨(최대 64자). 예: "국가장학금", "인턴 모집". 없으면 null.
- summary: 공지 요약(선택).
- schedules: 일정 목록. 아래 "비대칭 날짜 처리" 규칙을 따르세요. 각 항목에 kind(일정 종류), label(예: 서류 마감, 1차 면접), starts_at/ends_at 또는 *_date_raw 포함.
- raw_eligibility_text, eligibility_rules, target_departments, target_grades: 아래 "자격 요건 추출" 규칙과 **필드 순서**를 지키세요.
- hashtags, pipeline_version("v1"), metadata.

---

## 비대칭 날짜 처리 (Asymmetric Fuzzy Date)
- 시작일과 종료일을 **독립적으로** 평가하세요. 한쪽만 파싱 가능해도 그쪽은 반드시 채우세요.
- **한쪽만 명확한 경우**: 명확한 쪽은 ISO8601(starts_at 또는 ends_at)로 채우고, 모호한 쪽은 null로 두고 **해당 원문만** start_date_raw 또는 end_date_raw에 보존하세요.
  - 예: "2026.02.01 ~ 채용 시 마감" → starts_at=2026-02-01T00:00:00+09:00, ends_at=null, end_date_raw="채용 시 마감".
- **둘 다 모호한 경우**: starts_at/ends_at은 null로 두고, date_raw 또는 start_date_raw/end_date_raw에 원문만 넣으세요(예: "11월 중순", "추후 공지").
- 각 일정은 kind(application_deadline, interview, result, event, other), label(사람이 읽기 좋은 라벨)을 함께 채우세요.

---

## 자격 요건 추출 (제한 조건 기반)
**엄격한 제한 조건이 문단에 있을 때만** 자격 관련 필드를 채우세요. 그 외에는 전부 null/빈 리스트로 두세요.

1. **추출 대상이 되는 경우** (다음 중 하나라도 문단에 있을 때만):
   - 학년 제한(예: 3학년 이상, 대학원생만)
   - 학과/전공 제한
   - 학점·성적 커트라인
   - 지원 자격·참석 자격·수혜 자격을 **판가름하는** 조건
2. **추출하지 않는 경우**: "안내를 받아야 하는 대상", "대상자에게 안내"처럼 **판별 조건 없이 수신 대상만** 언급된 경우.
   - 이 경우 raw_eligibility_text=null, eligibility_rules=[], target_departments=[], target_grades=[] 로 두세요.

**필드 순서(Schema-driven CoT)** — 자격을 채울 때는 반드시 아래 순서로 채우세요. 원문을 먼저 발췌한 뒤 분절·학과·학년을 채우면 환각이 줄어듭니다.
1. raw_eligibility_text: 본문의 자격 관련 문장을 **가공 없이 그대로** 발췌. 없으면 null.
2. eligibility_rules: 위 원문을 바탕으로 분절한 자격 조건 리스트.
3. target_departments: 위 자격 요건에 명시된 학과 리스트. "없음", "알 수 없음", "해당없음" 등 플레이스홀더 사용 금지. 해당 없으면 빈 리스트.
4. target_grades: 위 자격 요건에 명시된 학년. 1~6, all, grad_master, grad_phd, grad_all, other 중 선택. 없으면 빈 리스트."""


def _get_instructor_client():
    import instructor

    api_key = None
    if settings.gemini_api_key:
        api_key = settings.gemini_api_key.get_secret_value()
    provider = f"google/{settings.gemini_model}"
    if api_key:
        return instructor.from_provider(provider, api_key=api_key, max_retries=0)
    return instructor.from_provider(provider, max_retries=0)


def extract_notice_structured(html_content: str) -> NoticeAIExtraction:
    """
    HTML 공지 본문에서 NoticeAIExtraction 구조화 추출.
    Instructor + Gemini 사용. 검증 실패 시 호출자가 처리(재시도/폴백).
    """
    client = _get_instructor_client()
    response = client.create(
        messages=[
            {"role": "system", "content": EXTRACTOR_SYSTEM_PROMPT},
            {"role": "user", "content": html_content[:100_000] or "(내용 없음)"},
        ],
        response_model=NoticeAIExtraction,
        max_retries=0,
    )
    return response
