import secrets
from typing import Final

from app.core.config import settings


class InternalAuthError(Exception):
    """Base exception for internal authentication failures."""


class CrawlTriggerNotConfiguredError(InternalAuthError):
    """CRAWL_TRIGGER_SECRET is missing or empty."""


class InvalidCrawlTriggerSecretError(InternalAuthError):
    """Provided crawl trigger secret does not match expected value."""


_BEARER_PREFIX: Final[str] = "Bearer "


def _extract_provided_secret(
    x_crawl_trigger_secret: str | None,
    authorization: str | None,
) -> str:
    """
    Extract provided crawl trigger secret from headers.

    Preference order:
    1. X-Crawl-Trigger-Secret
    2. Authorization: Bearer <token>
    """
    if x_crawl_trigger_secret:
        return x_crawl_trigger_secret
    if authorization and authorization.startswith(_BEARER_PREFIX):
        return authorization[len(_BEARER_PREFIX) :].strip()
    return ""


def check_crawl_trigger_secret(
    x_crawl_trigger_secret: str | None,
    authorization: str | None,
) -> None:
    """
    Validate provided secret against CRAWL_TRIGGER_SECRET.

    Raises:
        CrawlTriggerNotConfiguredError: when expected secret is not configured.
        InvalidCrawlTriggerSecretError: when provided secret is missing or invalid.
    """
    if not settings.crawl_trigger_secret:
        raise CrawlTriggerNotConfiguredError("Crawl trigger not configured (CRAWL_TRIGGER_SECRET missing)")
    provided = _extract_provided_secret(x_crawl_trigger_secret, authorization)
    expected = settings.crawl_trigger_secret.get_secret_value()
    if not secrets.compare_digest(provided, expected):
        raise InvalidCrawlTriggerSecretError("Invalid or missing crawl trigger secret")
