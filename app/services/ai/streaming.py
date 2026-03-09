from __future__ import annotations

"""
AI 공지 추출 Streaming/Partial 설계 초안.

- Draft/Partial 모델과 strict 모델(NoticeAIExtraction)을 분리해,
  Instructor의 Partial 스트리밍을 안전하게 사용할 수 있는 구조를 정의한다.
- 실제 엔드포인트/호출부는 후속 단계에서 연결한다.
"""

from typing import Generator

from instructor import Partial  # type: ignore[import]
from pydantic import BaseModel, Field

from app.domain.contracts.ai_extraction import NoticeAIExtraction, NoticeCategory
from app.services.ai.extractor import _get_instructor_client, EXTRACTOR_SYSTEM_PROMPT


class NoticeExtractionDraft(BaseModel):
    """
    Streaming 전용 Draft 모델.

    - strict validator(빈 schedule 금지, eligibility invariant 등)는 적용하지 않고,
      최종 단계에서 NoticeAIExtraction으로 한 번 더 검증한다.
    - 필드 shape는 NoticeAIExtraction과 최대한 유사하게 유지한다.
    """

    # Draft 단계에서는 모든 필드를 느슨하게 두고,
    # Partial[NoticeExtractionDraft]가 점진적으로 채워지도록 설계한다.
    # Instructor Partial 구현 제약으로, Union 타입 대신 단일 str 필드를 사용한다.
    category: str = Field(default="")
    sub_category: str = Field(default="")
    summary: str = Field(default="")
    # 나머지 필드들은 Partial 사용 시 LLM이 알아서 채우게 두고,
    # 최종 단계에서 NoticeAIExtraction으로 강타입 검증만 수행한다.


def stream_notice_extraction(
    html_content: str,
    image_urls: list[str] | None = None,
) -> Generator[Partial[NoticeExtractionDraft], None, NoticeAIExtraction]:
    """
    Draft/Partial → strict 모델로 이어지는 Streaming 구조 설계.

    사용 예시(콜러 입장):

    final: NoticeAIExtraction | None = None
    for partial in stream_notice_extraction(html, image_urls):
        # partial을 프론트에 전송해 progress UI 등에 사용
        final = partial.to_model()
    # 제너레이터의 return 값으로 strict NoticeAIExtraction을 받을 수 있도록 설계
    return final_strict
    """
    client = _get_instructor_client()

    # NOTE: 현재는 설계 초안 수준으로, 실제 호출부에서는
    # app.services.ai_pipeline._clean_notice_html 등을 재사용해
    # HTML 전처리를 수행한 뒤 이 함수에 전달하는 것이 바람직하다.

    # Instructor 공식 문서 기준 패턴:
    # for partial in client.create(
    #     response_model=Partial[DraftModel],
    #     messages=[...],
    #     stream=True,
    # ): ...

    from instructor.processing.multimodal import Image  # type: ignore[import]

    text = html_content[:100_000] or "(내용 없음)"
    urls = (image_urls or [])[:5]
    if not urls:
        user_content = text
    else:
        user_content = [
            text,
            "아래 이미지는 공지 본문(포스터·첨부 등)입니다. HTML과 함께 참고하여 지원자격·일정·날짜를 추출하세요.",
        ] + [
            Image.from_url(u)
            for u in urls
            if u and (u.startswith("http://") or u.startswith("https://"))
        ]

    final_model: NoticeExtractionDraft | None = None

    for partial in client.create(
        messages=[
            {"role": "system", "content": EXTRACTOR_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_model=Partial[NoticeExtractionDraft],
        stream=True,
    ):
        final_model = partial.to_model()
        yield partial

    # 최종 strict 검증 단계: Draft → NoticeAIExtraction
    if final_model is None:
        return NoticeAIExtraction()

    # 현재는 category/sub_category/summary 정도만 strict 모델에 반영하고,
    # 나머지 필드는 후속 단계에서 확장한다.
    category_value = (
        NoticeCategory(final_model.category)
        if final_model.category in {c.value for c in NoticeCategory}
        else NoticeCategory.OTHER
    )
    return NoticeAIExtraction(
        category=category_value,
        sub_category=final_model.sub_category,
        summary=final_model.summary,
        schedules=[],
        raw_eligibility_text=None,
        eligibility_rules=[],
        target_departments=[],
        target_grades=[],
        hashtags=[],
    )

