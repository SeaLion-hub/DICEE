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
