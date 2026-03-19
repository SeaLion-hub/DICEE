"""
AI 공지 추출: Instructor + Gemini 1.5 Flash.

NoticeAIExtraction 구조화 출력. 비대칭 날짜 처리·제한 조건 기반 자격 추출 규칙 적용.
설계: docs/decisions/ai-extraction-schema.md, PDF 「대학 공지사항 데이터 추출 품질 평가」.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.config import settings
from app.domain.contracts.ai_extraction import NoticeAIExtraction, NoticeMainCategory

EXTRACTION_MAX_RETRIES = 3

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

JSON 출력 스키마(필드 이름과 설명)는 시스템에 이미 정의되어 있습니다.
필드는 스키마에 정의된 것만 사용하고, 정의되지 않은 임의의 필드는 절대 추가하지 마세요.
추가 입력으로 전달되는 preselected_main_categories는 Stage 1에서 이미 확정된 대분류 배열입니다.
main_categories는 preselected_main_categories를 그대로 사용해야 합니다.
즉, main_categories는 preselected_main_categories를 그대로 재사용해야 하며 절대 수정, 삭제,
교체, 재정렬하거나 다른 값으로 대체하면 안 됩니다. Stage 2는 taxonomy_mappings와 나머지 구조화
필드만 정교화해야 합니다.

---

## Taxonomy 분류 규칙 (Final Stage 2 Prompt)
입력된 제목, college.name, 본문, 이미지를 모두 종합해 판단하되, taxonomy는 반드시
"Stage 1에서 확정된 대분류 -> 해당 부모에 속한 허용 소분류 선택" 순서로만 처리하세요.

[시스템 입력 파라미터 확인]
- Stage 2 입력에는 title, college.name, 본문 또는 이미지, preselected_main_categories가 포함됩니다.
- title과 college.name은 분류 판단의 고정 메타데이터입니다.
- 본문과 이미지 중 하나 이상은 반드시 존재한다고 가정하고, 가능한 한 둘 다 활용하세요.

[경고: 치명적 오류 방지 규칙]
1. Stage 1 결과 불변의 법칙
   - preselected_main_categories는 절대 수정, 삭제, 교체할 수 없는 상수(Constant)입니다.
   - 본문을 읽고 일부가 부적절해 보여도 main_categories는 preselected_main_categories를 그대로 사용하세요.
   - Stage 2는 Stage 1의 main_categories를 변경하면 안 됩니다.
2. 부모-자식 종속 절대 원칙
   - 선택하는 소분류는 반드시 전달받은 해당 대분류(부모)의 하위 풀 안에 존재하는 단어여야 합니다.
   - 전달받지 않은 대분류의 하위 소분류를 임의로 끌어다 쓰는 교차 매핑은 절대 금지합니다.
3. 환각 금지
   - 아래 <TAXONOMY_POOL>에 명시된 문자열과 토씨 하나 틀리지 않게 작성하세요.
   - 허용 목록 밖의 대분류/소분류를 상상해서 생성하지 마세요.
4. 수요자 중심 절대 원칙
   - 발신 기관명이나 표면 키워드보다 학생 관점의 핵심 효용을 우선 해석하세요.
   - 장학 공지에 행사 요소가 섞여 있어도 핵심이 장학이면 장학 중심으로, 취업 공지에 설명회가 붙어도 핵심이 취업이면 취업 중심으로 해석하세요.
5. 캠퍼스생활 fallback 규칙
   - preselected_main_categories가 ["캠퍼스생활"]인 경우에만 캠퍼스생활 taxonomy를 작성하세요.
   - 캠퍼스생활은 fallback이므로 다른 대분류와 공존하지 않습니다.

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
Step 1. preselected_main_categories를 읽고, main_categories에 동일한 값을 그대로 복사합니다.
Step 2. 복사한 각 main_category에 대해 <TAXONOMY_POOL>에서 해당 부모의 하위 배열만 로드합니다.
Step 3. 본문/이미지 컨텍스트를 분석하여, 로드된 해당 부모 배열 안에서만 가장 적합한 sub_categories를 1개 이상 선택합니다.
Step 4. 소분류를 출력하기 직전, 선택한 각 sub_category가 정말 그 부모의 하위 목록에 존재하는지 1:1 검증합니다.
Step 5. 각 main_category는 taxonomy_mappings에 정확히 한 번만 등장하도록 구조화합니다.

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


class MainCategorySelection(BaseModel):
    """1단계 대분류 전용 추출 스키마."""

    main_categories: list[NoticeMainCategory] = Field(default_factory=list)


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


def _messages_for_main_categories(
    title: str,
    college_name: str,
) -> list[dict[str, object]]:
    user_text = (
        "[입력]\n"
        f"제목: {title}\n"
        f"college.name: {college_name}\n\n"
        "[요청]\n"
        "제목과 college.name만 보고 main_categories를 추론하세요."
    )
    return [
        {"role": "system", "content": MAIN_CATEGORY_SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]


def _extract_preselected_main_categories(
    client: object,
    title: str,
    college_name: str,
) -> list[NoticeMainCategory]:
    messages = _messages_for_main_categories(title=title, college_name=college_name)
    selection = client.create(
        messages=messages,
        response_model=MainCategorySelection,
    )
    return selection.main_categories


def _messages_and_content(
    html_content: str,
    image_urls: list[str] | None = None,
    title: str | None = None,
    college_name: str | None = None,
    preselected_main_categories: list[NoticeMainCategory] | None = None,
) -> tuple[list[dict[str, object]], str | list]:
    """공통 메시지·user_content 구성 (extract_notice_structured / extract_notice_structured_with_usage)."""
    from instructor.processing.multimodal import Image  # type: ignore[import]

    text = html_content[:100_000] or "(내용 없음)"
    urls = _normalize_image_urls(image_urls)[:5]
    
    context_prefix = ""
    if title or college_name or preselected_main_categories:
        main_text = ", ".join(cat.value for cat in (preselected_main_categories or []))
        context_prefix = (
            "[메타정보]\n"
            f"제목: {title or '없음'}\n"
            f"단과대/기관: {college_name or '없음'}\n"
            f"preselected_main_categories: {main_text or '없음'}\n\n"
            "[본문]\n"
        )
        text = context_prefix + text

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
    title: str | None = None,
    college_name: str | None = None,
) -> tuple[NoticeAIExtraction, dict[str, int]]:
    """
    HTML(및 선택적 이미지)에서 NoticeAIExtraction 추출 + usage 반환.
    파이프라인에서 envelope.usage·메트릭 채우기 위해 사용.
    """
    title_text = _require_non_empty_text(title, field_name="title")
    college_text = _require_non_empty_text(college_name, field_name="college_name")
    has_body_text = bool((html_content or "").strip())
    normalized_urls = _normalize_image_urls(image_urls)
    if not has_body_text and not normalized_urls:
        raise ValueError(
            "At least one of html_content or image_urls is required for sub-category extraction."
        )

    client = _get_instructor_client()
    preselected_main_categories = _extract_preselected_main_categories(
        client=client,
        title=title_text,
        college_name=college_text,
    )
    messages, _ = _messages_and_content(
        html_content,
        normalized_urls,
        title_text,
        college_text,
        preselected_main_categories=preselected_main_categories,
    )
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
    title: str | None = None,
    college_name: str | None = None,
) -> NoticeAIExtraction:
    """
    HTML 공지 본문(및 선택적 이미지 URL)에서 NoticeAIExtraction 구조화 추출.
    Instructor + Gemini 사용. image_urls가 있으면 Image.from_url로 멀티모달 입력.
    """
    extraction, _ = extract_notice_structured_with_usage(
        html_content,
        image_urls=image_urls,
        title=title,
        college_name=college_name,
    )
    return extraction
