"""Gemini 텍스트 임베딩 (동기). Celery·asyncio.to_thread 공용."""

from __future__ import annotations

import logging
import types

from app.constants.embeddings import EMBEDDING_DIM, GEMINI_EMBEDDING_MODEL
from app.core.config import settings
from app.services.ai.exceptions import EmbeddingProviderError, EmbeddingProviderTransientError

logger = logging.getLogger(__name__)

_google_api_exceptions: types.ModuleType | None = None
try:
    from google.api_core import exceptions as _gae
except ImportError:  # pragma: no cover
    pass
else:
    _google_api_exceptions = _gae


def _configure_genai() -> None:
    import google.generativeai as genai

    if settings.gemini_api_key:
        genai.configure(api_key=settings.gemini_api_key.get_secret_value())


def embed_text_sync(text: str) -> list[float]:
    """
    단일 텍스트 임베딩. gemini_api_key 미설정 시 GOOGLE_API_KEY 환경 변수를 사용한다.
    """
    import google.generativeai as genai

    stripped = (text or "").strip()
    if not stripped:
        raise ValueError("text must be non-empty for embedding")

    _configure_genai()
    try:
        result = genai.embed_content(
            model=GEMINI_EMBEDDING_MODEL,
            content=stripped,
        )
    except Exception as e:
        if _google_api_exceptions is not None and isinstance(e, _google_api_exceptions.GoogleAPIError):
            logger.warning("embed_content Google API error", exc_info=True)
            raise EmbeddingProviderTransientError("embedding provider request failed") from e
        logger.warning("embed_content failed", exc_info=True)
        raise EmbeddingProviderTransientError("embedding request failed") from e

    emb: object = None
    if isinstance(result, dict):
        emb = result.get("embedding")
    else:
        emb = getattr(result, "embedding", None)

    if not isinstance(emb, list) or len(emb) != EMBEDDING_DIM:
        raise EmbeddingProviderError("embedding provider returned invalid vector shape")
    return [float(x) for x in emb]
