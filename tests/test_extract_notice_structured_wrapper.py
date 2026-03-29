"""extract_notice_structured 래퍼·입력 검증 (LLM 호출 없음)."""

from unittest.mock import patch

import pytest
from app.domain.contracts.ai_extraction import NoticeAIExtraction
from app.services.ai.extractor import extract_notice_structured
from app.services.ai.types import ExtractorCallStats, TokenUsage


def test_extract_notice_structured_requires_body_or_images() -> None:
    with pytest.raises(ValueError, match="At least one of html_content or image_urls"):
        extract_notice_structured("", image_urls=None, title="제목", college_name="공대")


def test_extract_notice_structured_returns_extraction_from_with_usage() -> None:
    fake = NoticeAIExtraction()
    stats = ExtractorCallStats()
    usage = TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2)
    with patch(
        "app.services.ai.extractor.extract_notice_structured_with_usage",
        return_value=(fake, usage, stats),
    ) as m:
        out = extract_notice_structured("<p>본문</p>", title="제목", college_name="공대")
    assert out is fake
    m.assert_called_once()
