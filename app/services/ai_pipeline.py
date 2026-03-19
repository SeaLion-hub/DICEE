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

from bs4 import BeautifulSoup, Comment
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
from app.domain.contracts.ai_extraction import (
    NoticeAIExtraction,
    NoticeMainCategory,
    TaxonomyMappingItem,
)
from app.services.ai.extractor import extract_notice_structured_with_usage

logger = logging.getLogger(__name__)

_AI_INPUT_HTML_CHAR_LIMIT = 12_000
_ALLOWED_SLIM_HTML_TAGS = {
    "article",
    "section",
    "main",
    "div",
    "p",
    "br",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "th",
    "td",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "span",
    "a",
    "img",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "pre",
    "code",
}
_DROP_HTML_TAGS = {
    "script",
    "style",
    "nav",
    "footer",
    "noscript",
}
_ALLOWED_HTML_ATTRS: dict[str, set[str]] = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
    "th": {"colspan", "rowspan", "scope"},
    "td": {"colspan", "rowspan"},
}


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
    공지 HTML을 slim_html(구조 보존 + 노이즈 제거)로 정제한다.

    - script/style/nav/footer/noscript 제거
    - 허용 태그 집합만 남기고, 나머지 태그는 unwrap
    - 태그별 허용 속성만 유지하여 노이즈(class/style/on*) 제거
    - img alt 텍스트를 본문에 주입해 이미지 기반 정보 손실 방지
    - 최종 slim_html 문자열 길이를 상한으로 제한
    """
    if not html_content or not html_content.strip():
        return ""

    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(_DROP_HTML_TAGS):
        tag.decompose()

    for node in soup.find_all(string=lambda t: isinstance(t, Comment)):
        node.extract()

    for img in soup.find_all("img"):
        alt = (img.get("alt") or "").strip()
        if alt:
            img.insert_before(f"[이미지: {alt}]")

    root = soup.body or soup
    for tag in list(root.find_all(True)):
        if tag.name not in _ALLOWED_SLIM_HTML_TAGS:
            tag.unwrap()
            continue

        allowed_attrs = _ALLOWED_HTML_ATTRS.get(tag.name, set())
        for attr in list(tag.attrs):
            if attr not in allowed_attrs:
                del tag.attrs[attr]

        if tag.name == "a":
            href = (tag.get("href") or "").strip()
            if href:
                tag["href"] = href
            elif "href" in tag.attrs:
                del tag.attrs["href"]
        elif tag.name == "img":
            src = (tag.get("src") or "").strip()
            alt = (tag.get("alt") or "").strip()
            if src:
                tag["src"] = src
            elif "src" in tag.attrs:
                del tag.attrs["src"]
            if alt:
                tag["alt"] = alt
            elif "alt" in tag.attrs:
                del tag.attrs["alt"]

    if getattr(root, "name", None) == "body":
        slim_html = root.decode_contents(formatter="html").strip()
    else:
        slim_html = str(root).strip()
    return slim_html[:_AI_INPUT_HTML_CHAR_LIMIT]


def _normalize_html_for_substring_validation(source_html: str) -> str:
    """substring 검증용: HTML을 안정적인 텍스트 표현으로 정규화."""
    if not source_html:
        return ""
    soup = BeautifulSoup(source_html, "html.parser")
    body_text = soup.get_text("\n")
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    return "\n".join(lines)


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


def validate_and_normalize_taxonomy(
    extraction: NoticeAIExtraction,
) -> NoticeAIExtraction:
    """
    LLM 출력 직후 taxonomy 무결성을 방어적으로 재검증/정규화한다.

    정책:
    - main_categories가 0개인 경우는 미분류로 허용한다(폴백 미사용).
    - main_categories가 하나 이상이면 taxonomy_mappings는 반드시 존재해야 한다.
    - 캠퍼스생활은 단독 대분류일 때만 허용한다.
    - 각 대분류는 taxonomy_mappings에 정확히 1번 등장해야 한다.
    - 소분류는 공백/중복을 정리한 뒤, 비어 있으면 실패 처리한다.
    - 소분류는 TaxonomyMappingItem 재검증으로 부모 풀 소속을 강제한다.
    """
    if not extraction.main_categories:
        # 0개 대분류는 "미분류"로 간주하고 파이프라인을 계속 진행한다.
        return extraction

    mains = extraction.main_categories
    if (
        NoticeMainCategory.CAMPUS_LIFE in mains
        and len(mains) > 1
    ):
        raise ValueError(
            "'캠퍼스생활' is a fallback main category and must be assigned as a single category only."
        )
    if not extraction.taxonomy_mappings:
        raise ValueError(
            "taxonomy_mappings are required when main_categories are provided."
        )

    normalized_mappings: list[TaxonomyMappingItem] = []
    seen_mains: set[NoticeMainCategory] = set()
    for item in extraction.taxonomy_mappings:
        if item.main_category in seen_mains:
            raise ValueError(
                "taxonomy_mappings must not contain duplicate main_category entries."
            )
        seen_mains.add(item.main_category)

        deduped_sub_categories: list[str] = []
        seen_subs: set[str] = set()
        for sub in item.sub_categories:
            text = (sub or "").strip()
            if not text or text in seen_subs:
                continue
            seen_subs.add(text)
            deduped_sub_categories.append(text)
        if not deduped_sub_categories:
            raise ValueError(
                f"taxonomy mapping for '{item.main_category.value}' must include at least one sub-category."
            )

        normalized_mappings.append(
            TaxonomyMappingItem(
                main_category=item.main_category,
                sub_categories=deduped_sub_categories,
            )
        )

    if set(mains) != {item.main_category for item in normalized_mappings}:
        raise ValueError(
            "main_categories and taxonomy_mappings must reference the same set of main categories."
        )

    return extraction.model_copy(update={"taxonomy_mappings": normalized_mappings})


def extract_notice_info(
    html_content: str,
    image_urls: list[str] | None = None,
    title: str | None = None,
    college_name: str | None = None,
) -> ExtractionEnvelope:
    """
    HTML 공지 본문(및 선택적 이미지 URL)에서 NoticeAIExtraction 구조화 추출.

    - HTML을 slim_html로 전처리해 구조를 보존하면서 노이즈를 줄인다.
    - Instructor 레이어(_get_instructor_client)에서 max_retries로 self-correction 수행.
    - 여기서는 별도 재시도를 수행하지 않고, ValidationError/InstructorRetryException을
      fallback Envelope로 변환한다.
    """
    started_at = time.monotonic()
    raw_html = html_content or ""
    html_raw_len = len(raw_html)
    slim_html = _clean_notice_html(raw_html)
    # html_clean_len 키는 하위 호환을 위해 유지하고, 값은 slim_html 길이 기준으로 해석한다.
    html_clean_len = len(slim_html)
    # 전처리 결과가 비어 있으면 raw_html로 폴백하고, 그렇지 않으면 slim_html을 사용한다.
    prompt_html = slim_html or raw_html
    validation_source = _normalize_html_for_substring_validation(prompt_html)
    image_count = len(image_urls or [])
    provider = f"google/{settings.gemini_model}"
    model = settings.gemini_model
    increment(AI_EXTRACTION_ATTEMPT_TOTAL)
    try:
        extraction, usage = extract_notice_structured_with_usage(
            prompt_html,
            image_urls=image_urls,
            title=title,
            college_name=college_name,
        )
        try:
            extraction = validate_and_normalize_taxonomy(extraction)
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
                    "fallback_reason": "taxonomy_validation_failed",
                    "html_raw_len": html_raw_len,
                    "html_clean_len": html_clean_len,
                    "image_count": image_count,
                    "elapsed_ms": elapsed_ms,
                },
            )
        if getattr(settings, "ai_extraction_enforce_raw_substrings", False) and not (
            image_urls or []
        ):
            try:
                validate_extraction_raw_substrings(extraction, validation_source)
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
    - taxonomy_rows: notice_taxonomy_mappings 행 단위 매핑(main_category, sub_category)
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
    taxonomy_rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in extraction.taxonomy_mappings:
        main_value = item.main_category.value
        for sub in item.sub_categories:
            sub_value = (sub or "").strip()
            if not sub_value:
                continue
            key = (main_value, sub_value)
            if key in seen:
                continue
            seen.add(key)
            taxonomy_rows.append(
                {
                    "main_category": main_value,
                    "sub_category": sub_value,
                }
            )
    return {
        "ai_extracted_json": raw,
        "dates": dates,
        "eligibility": extraction.eligibility_rules,
        "hashtags": extraction.hashtags,
        "taxonomy_rows": taxonomy_rows,
    }
