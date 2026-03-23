"""AI 추출 메트릭 계측 검증 (attempt/success/fallback/provider_error/tokens)."""

from unittest.mock import patch

import pytest
from app.core.metrics import (
    AI_EXTRACTION_ATTEMPT_TOTAL,
    AI_EXTRACTION_FALLBACK_TOTAL,
    AI_EXTRACTION_PROVIDER_ERROR_TOTAL,
    AI_EXTRACTION_SUCCESS_TOTAL,
    AI_EXTRACTION_TOKENS_TOTAL,
    AI_EXTRACTION_VALIDATION_ERROR_TOTAL,
    get_counter,
)
from app.domain.contracts.ai_extraction import NoticeAIExtraction
from app.services.ai.types import TokenUsage
from app.services.ai_pipeline import extract_notice_info
from pydantic import ValidationError


def test_extract_notice_info_success_increments_attempt_and_success() -> None:
    """성공 시 ATTEMPT, SUCCESS가 1씩 증가한다."""
    stub = NoticeAIExtraction(target_departments=[])
    with patch(
        "app.services.ai_pipeline.extract_notice_structured_with_usage",
        return_value=(stub, TokenUsage()),
    ):
        extract_notice_info("<p>html</p>")
    assert get_counter(AI_EXTRACTION_ATTEMPT_TOTAL) >= 1
    assert get_counter(AI_EXTRACTION_SUCCESS_TOTAL) >= 1


def test_extract_notice_info_validation_fallback_increments_fallback_and_validation_error() -> None:
    """ValidationError fallback 시 FALLBACK, VALIDATION_ERROR가 증가한다."""

    def _raise_validation(*args, **kwargs):
        raise ValidationError.from_exception_data("NoticeAIExtraction", [])

    with patch(
        "app.services.ai_pipeline.extract_notice_structured_with_usage",
        side_effect=_raise_validation,
    ):
        extract_notice_info("<p>html</p>")
    assert get_counter(AI_EXTRACTION_FALLBACK_TOTAL) >= 1
    assert get_counter(AI_EXTRACTION_VALIDATION_ERROR_TOTAL) >= 1


def test_extract_notice_info_success_populates_usage_and_increments_tokens_total() -> None:
    """성공 시 반환된 usage가 envelope.usage에 들어가고, total_tokens만큼 AI_EXTRACTION_TOKENS_TOTAL이 증가한다."""
    stub = NoticeAIExtraction(target_departments=[])
    usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    with patch(
        "app.services.ai_pipeline.extract_notice_structured_with_usage",
        return_value=(stub, usage),
    ):
        envelope = extract_notice_info("<p>html</p>")
    assert envelope.usage.prompt_tokens == 100
    assert envelope.usage.completion_tokens == 50
    assert envelope.usage.total_tokens == 150
    assert get_counter(AI_EXTRACTION_TOKENS_TOTAL) >= 150


def test_extract_notice_info_provider_error_increments_provider_error() -> None:
    """Provider 계열 예외 전파 전에 PROVIDER_ERROR가 증가한다."""
    with patch(
        "app.services.ai_pipeline.extract_notice_structured_with_usage",
        side_effect=RuntimeError("network"),
    ):
        with pytest.raises(RuntimeError):
            extract_notice_info("<p>html</p>")
    assert get_counter(AI_EXTRACTION_PROVIDER_ERROR_TOTAL) >= 1
