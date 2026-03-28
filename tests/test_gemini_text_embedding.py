"""gemini_text_embedding: 업스트림 오류 래핑."""

from unittest.mock import patch

import pytest

pytest.importorskip("google.api_core.exceptions")

from app.services.gemini_text_embedding import EmbeddingProviderError, embed_text_sync  # noqa: E402
from google.api_core import exceptions as gae  # noqa: E402


def test_embed_text_sync_wraps_google_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """GoogleAPIError는 EmbeddingProviderError로 흡수한다 (라우터·503 매핑 일관성)."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "gemini_api_key", None)
    with (
        patch("app.services.gemini_text_embedding._configure_genai", lambda: None),
        patch(
            "google.generativeai.embed_content",
            side_effect=gae.ResourceExhausted("rate limited"),
        ),
    ):
        with pytest.raises(EmbeddingProviderError, match="embedding provider request failed"):
            embed_text_sync("hello")
