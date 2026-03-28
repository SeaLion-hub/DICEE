"""
AI 공지 추출: Instructor + Gemini (single-pass structured output).

NoticeAIExtraction 구조화 출력. 비대칭 날짜 처리·제한 조건 기반 자격 추출 규칙 적용.
설계: docs/decisions/ai-extraction-schema.md, docs/decisions/ai-cost-limits.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from app.core.config import settings
from app.domain.contracts.ai_extraction import NoticeAIExtraction, NoticeMainCategory
from app.services.ai.types import (
    ExtractorCallStats,
    InstructorExtractionClient,
    TokenUsage,
)

if TYPE_CHECKING:
    from instructor.processing.multimodal import Image

# Kept for tests and docs; single-pass uses EXTRACTOR_SYSTEM_PROMPT only.
MAIN_CATEGORY_SYSTEM_PROMPT = """당신은 연세대학교 공지사항의 대분류를 선별하는 최고 수준의 정밀 분류기입니다.
입력으로 주어지는 정보는 오직 [제목]과 [college.name(발신 기관명)]뿐입니다.
당신의 유일한 임무는 이 정보만 바탕으로 아래 정의된 <ALLOWED_MAIN_CATEGORIES> 안에서만
대분류를 추출하여 JSON 형식으로 반환하는 것입니다.

[경고: 시스템 무결성 제약]
아래 <ALLOWED_MAIN_CATEGORIES>에 명시된 8개의 문자열 외에 단 한 글자라도 임의의 단어를
생성하면 시스템 파이프라인이 즉시 붕괴됩니다. 상상 생성은 절대 금지합니다.

<ALLOWED_MAIN_CATEGORIES>
- 학사/졸업
- 장학/지원
- 진로/취업
- 국제/교류
- 연구/실험
- 대회/공모전
- 문화/행사
- 캠퍼스생활
</ALLOWED_MAIN_CATEGORIES>

[분류 규칙 및 알고리즘]
1. 수요자 중심 절대 원칙
   - 발신 기관명에 속지 마세요. 국제처에서 올린 장학 공지의 핵심은 국제처가 아니라 장학일 수 있습니다.
   - 단순 행정 시스템 점검, 시설 운영 안내처럼 수요자의 직접적인 7대 핵심 편익
     (학사/장학/취업/국제/연구/대회/행사)과 무관한 공지는 모두 '캠퍼스생활'로 분류하세요.
2. 다중 할당 규칙
   - 복합적인 목적의 공지는 최대 3개까지 대분류를 선택할 수 있습니다.
3. 캠퍼스생활 배타 게이트
   - '캠퍼스생활'은 다른 7개 명확한 분류에 해당하지 않을 때만 선택하는 최후의 fallback입니다.
   - 만약 '캠퍼스생활'을 선택해야 한다고 판단했다면 다른 대분류와 절대 함께 할당하지 마세요.
   - 이 경우 오직 ["캠퍼스생활"] 단독 1개만 반환해야 합니다.
4. 출력 제한
   - 결과는 main_categories만 반환합니다.
   - 스키마에 없는 필드나 설명 문장은 추가하지 마세요.
"""

EXTRACTOR_SYSTEM_PROMPT = """당신은 대학 공지 HTML에서 구조화된 정보를 추출하고, 대분류-소분류 taxonomy를
엄격하게 매핑하는 전문 도우미입니다.
한국 대학 공지이므로 모든 날짜·시간은 **KST(Asia/Seoul)** 기준으로 해석하세요.
제공된 이미지(포스터·첨부 등)가 있으면 그 내용도 참고하여 일정·자격·날짜를 추출하세요.
입력 본문은 노이즈를 줄인 구조 보존 slim HTML일 수 있습니다.
table, ul/ol/li, p/br 같은 구조를 의미 단서로 해석하세요.
HTML 태그를 그대로 복사하지 말고, 구조를 읽어 일정·자격·taxonomy 정보를 추출하세요.

JSON 출력 스키마(필드 이름과 설명)는 시스템에 이미 정의되어 있습니다.
필드는 스키마에 정의된 것만 사용하고, 정의되지 않은 임의의 필드는 절대 추가하지 마세요.

---

## 대분류(main_categories) 선정
입력으로 [제목], [college.name], 본문(slim HTML), 선택적 이미지를 모두 참고하세요.

[경고: 시스템 무결성 제약]
아래 <ALLOWED_MAIN_CATEGORIES>에 명시된 8개의 문자열 외에 임의의 대분류 문자열을 생성하지 마세요.

<ALLOWED_MAIN_CATEGORIES>
- 학사/졸업
- 장학/지원
- 진로/취업
- 국제/교류
- 연구/실험
- 대회/공모전
- 문화/행사
- 캠퍼스생활
</ALLOWED_MAIN_CATEGORIES>

[대분류 규칙]
1. 수요자 중심 절대 원칙: 발신 기관명보다 학생에게 주는 실질 효용(학사/장학/취업 등)을 우선합니다.
2. 다중 할당: 복합 목적이면 최대 3개까지 main_categories를 선택할 수 있습니다.
3. 캠퍼스생활 배타 게이트: '캠퍼스생활'은 다른 7개에 해당하지 않을 때만 선택합니다.
   캠퍼스생활을 고르면 오직 ["캠퍼스생활"] 단독만 반환합니다.
4. main_categories와 taxonomy_mappings에 등장하는 대분류 집합은 반드시 일치해야 합니다.

---

## Taxonomy 분류 규칙
제목·기관·본문·이미지를 종합해 main_categories를 확정한 뒤, 각 대분류에 대해 허용 소분류 풀에서만 선택하세요.

[경고: 치명적 오류 방지 규칙]
1. 부모-자식 종속: 소분류는 선택한 대분류(부모)의 하위 풀 안에만 있어야 합니다. 교차 매핑 금지.
2. 환각 금지: <TAXONOMY_POOL> 문자열과 토씨 하나 틀리지 않게 작성하세요.
3. 수요자 중심: 장학+행사가 섞여 있으면 핵심이 장학이면 장학 중심으로 해석합니다.
4. 캠퍼스생활은 다른 대분류와 공존하지 않습니다.

<TAXONOMY_POOL>
{
  "학사/졸업": ["수강/학점", "휴학/복학", "전공/이중전공", "졸업/수료", "학사일정"],
  "장학/지원": ["교내/성적장학", "가계지원/국가장학", "근로/활동장학", "외부장학"],
  "진로/취업": ["채용/인턴", "진로/프로그램", "고시/자격증", "창업지원"],
  "국제/교류": ["교환/방문학생", "단기연수/캠프", "유학생지원", "어학프로그램"],
  "연구/실험": ["학부연구생(인턴)", "대학원진학", "연구과제/참여", "실험실안전"],
  "대회/공모전": ["교내경진대회", "외부공모전", "해커톤/아이디어"],
  "문화/행사": ["특강/세미나", "축제/공연", "동아리/학생회", "봉사활동"],
  "캠퍼스생활": ["시설/공간대여", "IT/시스템안내", "보건/복지", "기타안내"]
}
</TAXONOMY_POOL>

[매핑 알고리즘 의사코드]
Step 1. 제목·기관·본문·이미지를 바탕으로 main_categories를 위 규칙에 따라 선택합니다.
Step 2. 각 main_category에 대해 <TAXONOMY_POOL>에서 해당 부모의 하위 배열만 로드합니다.
Step 3. 본문/이미지 컨텍스트를 분석하여, 로드된 해당 부모 배열 안에서만
    가장 적합한 sub_categories를 1개 이상 선택합니다.
Step 4. 소분류를 출력하기 직전, 선택한 각 sub_category가 그 부모의 하위 목록에 존재하는지 1:1 검증합니다.
Step 5. 각 main_category는 taxonomy_mappings에 정확히 한 번만 등장하도록 구조화합니다.

---

## 비대칭 날짜 처리 (Asymmetric Fuzzy Date)
- 시작일과 종료일을 **독립적으로** 평가하세요. 한쪽만 파싱 가능해도 그쪽은 반드시 채우세요.
- **한쪽만 명확한 경우**: 명확한 쪽은 ISO8601(starts_at 또는 ends_at)로 채우고,
  모호한 쪽은 null로 두고 **해당 원문만** start_date_raw 또는 end_date_raw에 보존하세요.
  - 예: "2026.02.01 ~ 채용 시 마감" → starts_at=2026-02-01T00:00:00+09:00, ends_at=null, end_date_raw="채용 시 마감".
- **둘 다 모호한 경우**: starts_at/ends_at은 null로 두고,
  date_raw 또는 start_date_raw/end_date_raw에 원문만 넣으세요(예: "11월 중순", "추후 공지").
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
1. raw_eligibility_text: 본문의 자격 관련 문장을 **가공 없이 그대로** 발췌(스키마 최대 길이 내). 없으면 null.
2. eligibility_rules: 위 원문을 바탕으로 분절한 자격 조건 리스트.
3. target_departments: 위 자격 요건에 명시된 학과 리스트.
   "없음", "알 수 없음", "해당없음" 등 플레이스홀더 사용 금지. 해당 없으면 빈 리스트.
4. target_grades: 위 자격 요건에 명시된 학년.
   1~6, all, grad_master, grad_phd, grad_all, other 중 선택. 없으면 빈 리스트.

summary 필드는 꼭 필요할 때만 짧게(한두 문장) 작성하세요. 불필요하면 null로 두세요.
"""


class MainCategorySelection(BaseModel):
    """레거시 1단계 스키마(호환·테스트 참조). 단일 패스 경로에서는 사용하지 않습니다."""

    main_categories: list[NoticeMainCategory] = Field(default_factory=list)


def html_plain_text_length(html: str) -> int:
    """Slim HTML에서 태그를 제외한 연속 텍스트 길이(비교·라우팅용)."""
    if not html or not html.strip():
        return 0
    return len(BeautifulSoup(html, "html.parser").get_text(separator="", strip=False).strip())


def _require_non_empty_text(value: str | None, *, field_name: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required.")
    return text


def _normalize_image_urls(image_urls: list[str] | None) -> list[str]:
    return [
        u
        for u in (image_urls or [])
        if isinstance(u, str) and u and (u.startswith("http://") or u.startswith("https://"))
    ]


def apply_vision_image_gate(
    html_content: str,
    image_urls: list[str] | None,
    title: str,
) -> tuple[list[str], bool]:
    """
    Vision 입력에 넣을 URL 목록과, 멀티모달 사용 여부를 반환합니다.

    게이트가 꺼지면 기존과 같이 최대 5장까지 전달합니다.
    """
    normalized = _normalize_image_urls(image_urls)
    raw_count = len(normalized)
    if raw_count == 0:
        return [], False

    if not getattr(settings, "ai_vision_gate_enabled", True):
        capped = normalized[:5]
        return capped, len(capped) > 0

    body_len = html_plain_text_length(html_content)
    active_cap = int(getattr(settings, "ai_vision_max_images_active", 5) or 5)
    passive_cap = int(getattr(settings, "ai_vision_max_images_passive", 0) or 0)

    if body_len == 0:
        out = normalized[:active_cap]
        return out, len(out) > 0

    threshold = int(getattr(settings, "ai_vision_body_char_threshold", 400) or 0)
    if body_len < threshold:
        out = normalized[:active_cap]
        return out, len(out) > 0

    title_lower = (title or "").lower()
    for part in str(getattr(settings, "ai_vision_title_keyword_substrings", "") or "").split(","):
        p = part.strip().lower()
        if p and p in title_lower:
            out = normalized[:active_cap]
            return out, len(out) > 0

    out = normalized[:passive_cap]
    return out, passive_cap > 0


def _get_instructor_client(*, model: str | None = None) -> InstructorExtractionClient:
    """Instructor 클라이언트 팩토리 (Gemini 구조화 출력)."""
    import instructor  # type: ignore[import]

    api_key = None
    if settings.gemini_api_key:
        api_key = settings.gemini_api_key.get_secret_value()
    model_id = (model or settings.gemini_model or "").strip() or settings.gemini_model
    provider = f"google/{model_id}"
    kwargs: dict[str, object] = {}
    if api_key:
        kwargs["api_key"] = api_key
    return cast(
        InstructorExtractionClient,
        instructor.from_provider(provider, **kwargs),  # type: ignore[call-overload]
    )


def _messages_and_content(
    html_content: str,
    gated_image_urls: list[str],
    title: str | None = None,
    college_name: str | None = None,
) -> tuple[list[dict[str, object]], str | list[str | Image]]:
    """단일 패스용 user 메시지 구성."""
    from instructor.processing.multimodal import Image  # type: ignore[import]

    text = html_content if html_content else ""
    if len(text) > 150_000:
        text = text[:150_000]
    text = text or "(내용 없음)"

    context_prefix = ""
    if title or college_name:
        context_prefix = (
            "[메타정보]\n" f"제목: {title or '없음'}\n" f"단과대/기관: {college_name or '없음'}\n\n" "[본문]\n"
        )
        text = context_prefix + text

    if not gated_image_urls:
        user_content: str | list[str | Image] = text
    else:
        user_content = [
            text,
            "아래 이미지는 공지 본문(포스터·첨부 등)입니다. HTML과 함께 참고하여 지원자격·일정·날짜를 추출하세요.",
        ] + [Image.from_url(u) for u in gated_image_urls]
    messages: list[dict[str, object]] = [
        {"role": "system", "content": EXTRACTOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    return messages, user_content


def _usage_from_completion(completion: object) -> TokenUsage:
    """completion.usage를 TokenUsage로 변환."""
    prompt = 0
    completion_tokens = 0
    total = 0
    usage = getattr(completion, "usage", None)
    if usage is not None:
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total = int(getattr(usage, "total_tokens", 0) or 0)
    if total == 0 and (prompt or completion_tokens):
        total = prompt + completion_tokens
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion_tokens,
        total_tokens=total,
    )


def _max_retries_kw() -> dict[str, Any]:
    n = int(getattr(settings, "ai_extraction_max_retries", 3) or 0)
    if n <= 0:
        return {}
    return {"max_retries": n}


def _run_single_extraction_call(
    client: InstructorExtractionClient,
    messages: list[dict[str, object]],
) -> tuple[NoticeAIExtraction, TokenUsage]:
    mr = _max_retries_kw()
    create_with_completion = getattr(client, "create_with_completion", None)
    if create_with_completion is not None:
        try:
            extraction, completion = create_with_completion(
                messages=messages,
                response_model=NoticeAIExtraction,
                **mr,
            )
        except TypeError:
            extraction, completion = create_with_completion(
                messages=messages,
                response_model=NoticeAIExtraction,
            )
        return extraction, _usage_from_completion(completion)
    try:
        extraction = client.create(
            messages=messages,
            response_model=NoticeAIExtraction,
            **mr,
        )
    except TypeError:
        extraction = client.create(
            messages=messages,
            response_model=NoticeAIExtraction,
        )
    return extraction, TokenUsage()


def extract_notice_structured_with_usage(
    html_content: str,
    image_urls: list[str] | None = None,
    title: str | None = None,
    college_name: str | None = None,
    *,
    model: str | None = None,
) -> tuple[NoticeAIExtraction, TokenUsage, ExtractorCallStats]:
    """
    HTML(및 선택적 이미지)에서 NoticeAIExtraction 추출 + usage + 게이트 메타.

    단일 LLM 호출(Instructor + Gemini). Vision은 설정·휴리스틱에 따라 제한될 수 있습니다.
    """
    title_text = _require_non_empty_text(title, field_name="title")
    college_text = _require_non_empty_text(college_name, field_name="college_name")
    normalized_urls = _normalize_image_urls(image_urls)
    has_body_text = bool((html_content or "").strip())
    if not has_body_text and not normalized_urls:
        raise ValueError("At least one of html_content or image_urls is required for sub-category extraction.")

    gated_urls, vision_used = apply_vision_image_gate(html_content, image_urls, title_text)
    model_id = (model or settings.gemini_model or "").strip() or settings.gemini_model
    client = _get_instructor_client(model=model_id)
    messages, _ = _messages_and_content(
        html_content,
        gated_urls,
        title_text,
        college_text,
    )
    extraction, usage = _run_single_extraction_call(client, messages)
    stats = ExtractorCallStats(
        vision_used=vision_used,
        vision_image_count=len(gated_urls),
        raw_image_url_count=len(normalized_urls),
        llm_calls=1,
        model_id=model_id,
        escalated=False,
    )
    return extraction, usage, stats


def extract_notice_structured(
    html_content: str,
    image_urls: list[str] | None = None,
    title: str | None = None,
    college_name: str | None = None,
) -> NoticeAIExtraction:
    """
    HTML 공지 본문(및 선택적 이미지 URL)에서 NoticeAIExtraction 구조화 추출.
    Instructor + Gemini 사용. image_urls가 있으면 Image.from_url로 멀티모달 입력.
    """
    extraction, _, _ = extract_notice_structured_with_usage(
        html_content,
        image_urls=image_urls,
        title=title,
        college_name=college_name,
    )
    return extraction
