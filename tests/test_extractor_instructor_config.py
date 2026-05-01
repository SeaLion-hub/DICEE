"""Instructor 클라이언트 팩토리 설정(http timeout 등) 검증."""

from unittest.mock import MagicMock

import pytest


def test_get_instructor_client_passes_http_options_timeout_ms(monkeypatch: pytest.MonkeyPatch) -> None:
    import instructor
    from app.services.ai import extractor

    captured: dict[str, object] = {}

    def fake_from_provider(_model: str, **kwargs: object) -> MagicMock:
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(instructor, "from_provider", fake_from_provider)
    monkeypatch.setattr(extractor.settings, "ai_llm_request_timeout_seconds", 12.5)
    monkeypatch.setattr(extractor.settings, "gemini_api_key", None)
    monkeypatch.setattr(extractor.settings, "gemini_model", "gemini-2.0-flash")

    extractor._get_instructor_client(model="gemini-2.0-flash")

    assert captured.get("http_options") == {"timeout": 12500}


def test_single_extraction_call_disables_auto_safety_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.domain.contracts.ai_extraction import NoticeAIExtraction
    from app.services.ai import extractor
    from app.services.ai.types import TokenUsage

    captured: dict[str, object] = {}

    class FakeClient:
        def create_with_completion(self, **kwargs: object) -> tuple[NoticeAIExtraction, object]:
            captured.update(kwargs)
            completion = MagicMock()
            completion.usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
            return NoticeAIExtraction(target_departments=[]), completion

    monkeypatch.setattr(extractor.settings, "ai_extraction_max_retries", 1)

    extractor._run_single_extraction_call(FakeClient(), [{"role": "user", "content": "body"}])

    assert captured["safety_settings"] == []


def test_usage_from_completion_reads_gemini_usage_metadata() -> None:
    from app.services.ai import extractor

    completion = MagicMock()
    completion.usage = None
    completion.usage_metadata = {
        "prompt_token_count": 123,
        "candidates_token_count": 45,
        "total_token_count": 168,
    }

    usage = extractor._usage_from_completion(completion)

    assert usage.prompt_tokens == 123
    assert usage.completion_tokens == 45
    assert usage.total_tokens == 168


def test_usage_from_completion_reads_nested_raw_response_metadata() -> None:
    from app.services.ai import extractor

    completion = {
        "raw_response": {
            "usage_metadata": {
                "prompt_token_count": 20,
                "candidates_token_count": 7,
            }
        }
    }

    usage = extractor._usage_from_completion(completion)

    assert usage.prompt_tokens == 20
    assert usage.completion_tokens == 7
    assert usage.total_tokens == 27
