"""
AI 공지 추출: Instructor + Gemini 1.5 Flash.

NoticeAIExtraction 구조화 출력. 비대칭 날짜 처리·제한 조건 기반 자격 추출 규칙 적용.
설계: docs/decisions/ai-extraction-schema.md, PDF 「대학 공지사항 데이터 추출 품질 평가」.
"""

from __future__ import annotations

from app.core.config import settings
from app.domain.contracts.ai_extraction import NoticeAIExtraction

EXTRACTION_MAX_RETRIES = 3

EXTRACTOR_SYSTEM_PROMPT = """당신은 대학 공지 HTML에서 구조화된 정보를 추출하는 도우미입니다.
한국 대학 공지이므로 모든 날짜·시간은 **KST(Asia/Seoul)** 기준으로 해석하세요.
제공된 이미지(포스터·첨부 등)가 있으면 그 내용도 참고하여 일정·자격·날짜를 추출하세요.

JSON 출력 스키마(필드 이름과 설명)는 시스템에 이미 정의되어 있습니다.
필드는 스키마에 정의된 것만 사용하고, 정의되지 않은 임의의 필드는 절대 추가하지 마세요.

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

**필드 순서(Schema-driven CoT)** — 자격을 채울 때는 반드시 아래 순서로 채우세요.
1. raw_eligibility_text: 본문의 자격 관련 문장을 **가공 없이 그대로** 발췌. 없으면 null.
2. eligibility_rules: 위 원문을 바탕으로 분절한 자격 조건 리스트.
3. target_departments: 위 자격 요건에 명시된 학과 리스트. "없음", "알 수 없음", "해당없음" 등 플레이스홀더 사용 금지. 해당 없으면 빈 리스트.
4. target_grades: 위 자격 요건에 명시된 학년. 1~6, all, grad_master, grad_phd, grad_all, other 중 선택. 없으면 빈 리스트."""


def _get_instructor_client():
    """
    Instructor 클라이언트 팩토리.

    - Gemini 1.5 Flash 기반 구조화 출력 전용.
    - 재시도 정책(max_retries)은 Instructor 레이어에서만 관리하고,
      상위 ai_pipeline 레이어에서는 별도 재시도를 수행하지 않는다.
    """
    import instructor  # type: ignore[import]

    api_key = None
    if settings.gemini_api_key:
        api_key = settings.gemini_api_key.get_secret_value()
    provider = f"google/{settings.gemini_model}"
    kwargs: dict[str, object] = {"max_retries": EXTRACTION_MAX_RETRIES}
    if api_key:
        kwargs["api_key"] = api_key
    return instructor.from_provider(provider, **kwargs)


def _messages_and_content(
    html_content: str,
    image_urls: list[str] | None = None,
) -> tuple[list[dict[str, object]], str | list]:
    """공통 메시지·user_content 구성 (extract_notice_structured / extract_notice_structured_with_usage)."""
    from instructor.processing.multimodal import Image  # type: ignore[import]

    text = html_content[:100_000] or "(내용 없음)"
    urls = (image_urls or [])[:5]
    if not urls:
        user_content: str | list = text
    else:
        user_content = [
            text,
            "아래 이미지는 공지 본문(포스터·첨부 등)입니다. HTML과 함께 참고하여 지원자격·일정·날짜를 추출하세요.",
        ] + [Image.from_url(u) for u in urls if u and (u.startswith("http://") or u.startswith("https://"))]
    messages = [
        {"role": "system", "content": EXTRACTOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    return messages, user_content


def _usage_from_completion(completion: object) -> dict[str, int]:
    """completion.usage를 {prompt_tokens, completion_tokens, total_tokens} dict로 변환."""
    out: dict[str, int] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    usage = getattr(completion, "usage", None)
    if usage is None:
        return out
    out["prompt_tokens"] = int(getattr(usage, "prompt_tokens", 0) or 0)
    out["completion_tokens"] = int(getattr(usage, "completion_tokens", 0) or 0)
    out["total_tokens"] = int(getattr(usage, "total_tokens", 0) or 0)
    if out["total_tokens"] == 0 and (out["prompt_tokens"] or out["completion_tokens"]):
        out["total_tokens"] = out["prompt_tokens"] + out["completion_tokens"]
    return out


def extract_notice_structured_with_usage(
    html_content: str,
    image_urls: list[str] | None = None,
) -> tuple[NoticeAIExtraction, dict[str, int]]:
    """
    HTML(및 선택적 이미지)에서 NoticeAIExtraction 추출 + usage 반환.
    파이프라인에서 envelope.usage·메트릭 채우기 위해 사용.
    """
    messages, _ = _messages_and_content(html_content, image_urls)
    client = _get_instructor_client()
    if hasattr(client, "create_with_completion"):
        extraction, completion = client.create_with_completion(
            messages=messages,
            response_model=NoticeAIExtraction,
        )
        return extraction, _usage_from_completion(completion)
    extraction = client.create(
        messages=messages,
        response_model=NoticeAIExtraction,
    )
    return extraction, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def extract_notice_structured(
    html_content: str,
    image_urls: list[str] | None = None,
) -> NoticeAIExtraction:
    """
    HTML 공지 본문(및 선택적 이미지 URL)에서 NoticeAIExtraction 구조화 추출.
    Instructor + Gemini 사용. image_urls가 있으면 Image.from_url로 멀티모달 입력.
    """
    extraction, _ = extract_notice_structured_with_usage(html_content, image_urls=image_urls)
    return extraction
