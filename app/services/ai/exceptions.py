"""AI provider exception types used by Celery retry policy."""


class AIProviderRetryableError(Exception):
    """Transient LLM provider failure that should be retried by Celery."""


class EmbeddingProviderError(Exception):
    """Embedding provider failed or returned an invalid response."""


class EmbeddingProviderTransientError(EmbeddingProviderError):
    """Transient embedding provider failure that should be retried by Celery."""
