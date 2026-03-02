"""Standardized crawl error classification and monitoring hooks."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import httpx
from requests.exceptions import RequestException

from app.core.crawl_http import HtmlTooLargeError
from app.core.metrics import (
    DROP_REASON_BODY_TOO_LARGE,
    DROP_REASON_RETRYABLE_DONE,
    DROP_REASON_SKIPPABLE_HTTP,
)
from app.domain.contracts.crawl_contracts import CrawlLogContext
from app.services.crawl_policy import (
    HTTP_RETRY_STATUS_CODES,
    HTTP_RETRY_STATUS_MAX_5XX,
    HTTP_RETRY_STATUS_MIN_5XX,
    HTTP_SKIP_STATUS_CODES,
)

logger = logging.getLogger(__name__)


class CrawlErrorAction(str, Enum):
    DROP = "drop"
    PARSER = "parser"
    RAISE = "raise"


class CrawlErrorCategory(str, Enum):
    HTTP_403 = "http_403"
    HTTP_404 = "http_404"
    HTTP_SKIP = "http_skip"
    HTTP_RETRYABLE = "http_retryable"
    NETWORK = "network"
    BODY_TOO_LARGE = "body_too_large"
    SELECTOR_ERROR = "selector_error"
    FATAL_HTTP = "fatal_http"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CrawlErrorHandlingResult:
    action: CrawlErrorAction
    category: CrawlErrorCategory
    status_code: int | None
    drop_reason: str | None = None


class CrawlErrorHandler:
    """Classify crawl exceptions and emit uniform logging/Sentry metadata."""

    _PARSER_EXCEPTIONS = (ValueError, KeyError, AttributeError, TypeError)
    _NETWORK_EXCEPTIONS = (
        TimeoutError,
        OSError,
        ConnectionError,
        RequestException,
        httpx.HTTPError,
        httpx.TimeoutException,
    )

    def handle(
        self,
        exc: Exception,
        *,
        detail_url: str,
        ctx: CrawlLogContext,
        external_id: str | None = None,
    ) -> CrawlErrorHandlingResult:
        status = _status_code(exc)
        if isinstance(exc, HtmlTooLargeError):
            self._log(
                "crawl_error",
                category=CrawlErrorCategory.BODY_TOO_LARGE,
                action=CrawlErrorAction.DROP,
                status_code=status,
                detail_url=detail_url,
                exc=exc,
                ctx=ctx,
                external_id=external_id,
            )
            return CrawlErrorHandlingResult(
                action=CrawlErrorAction.DROP,
                category=CrawlErrorCategory.BODY_TOO_LARGE,
                status_code=status,
                drop_reason=DROP_REASON_BODY_TOO_LARGE,
            )

        if status in HTTP_SKIP_STATUS_CODES:
            category = CrawlErrorCategory.HTTP_404 if status == 404 else CrawlErrorCategory.HTTP_SKIP
            self._log(
                "crawl_error",
                category=category,
                action=CrawlErrorAction.DROP,
                status_code=status,
                detail_url=detail_url,
                exc=exc,
                ctx=ctx,
                external_id=external_id,
            )
            return CrawlErrorHandlingResult(
                action=CrawlErrorAction.DROP,
                category=category,
                status_code=status,
                drop_reason=DROP_REASON_SKIPPABLE_HTTP,
            )

        if status == 403:
            self._log(
                "crawl_error",
                category=CrawlErrorCategory.HTTP_403,
                action=CrawlErrorAction.DROP,
                status_code=status,
                detail_url=detail_url,
                exc=exc,
                ctx=ctx,
                external_id=external_id,
            )
            return CrawlErrorHandlingResult(
                action=CrawlErrorAction.DROP,
                category=CrawlErrorCategory.HTTP_403,
                status_code=status,
                drop_reason=DROP_REASON_RETRYABLE_DONE,
            )

        if status is not None and (
            status in HTTP_RETRY_STATUS_CODES
            or HTTP_RETRY_STATUS_MIN_5XX <= status <= HTTP_RETRY_STATUS_MAX_5XX
        ):
            self._log(
                "crawl_error",
                category=CrawlErrorCategory.HTTP_RETRYABLE,
                action=CrawlErrorAction.DROP,
                status_code=status,
                detail_url=detail_url,
                exc=exc,
                ctx=ctx,
                external_id=external_id,
            )
            return CrawlErrorHandlingResult(
                action=CrawlErrorAction.DROP,
                category=CrawlErrorCategory.HTTP_RETRYABLE,
                status_code=status,
                drop_reason=DROP_REASON_RETRYABLE_DONE,
            )

        if isinstance(exc, self._NETWORK_EXCEPTIONS):
            self._log(
                "crawl_error",
                category=CrawlErrorCategory.NETWORK,
                action=CrawlErrorAction.DROP,
                status_code=status,
                detail_url=detail_url,
                exc=exc,
                ctx=ctx,
                external_id=external_id,
            )
            return CrawlErrorHandlingResult(
                action=CrawlErrorAction.DROP,
                category=CrawlErrorCategory.NETWORK,
                status_code=status,
                drop_reason=DROP_REASON_RETRYABLE_DONE,
            )

        if isinstance(exc, self._PARSER_EXCEPTIONS):
            self._log(
                "crawl_error",
                category=CrawlErrorCategory.SELECTOR_ERROR,
                action=CrawlErrorAction.PARSER,
                status_code=status,
                detail_url=detail_url,
                exc=exc,
                ctx=ctx,
                external_id=external_id,
                include_trace=True,
            )
            self._capture_sentry(exc, ctx=ctx, detail_url=detail_url, category=CrawlErrorCategory.SELECTOR_ERROR)
            return CrawlErrorHandlingResult(
                action=CrawlErrorAction.PARSER,
                category=CrawlErrorCategory.SELECTOR_ERROR,
                status_code=status,
            )

        if status is not None:
            self._log(
                "crawl_error",
                category=CrawlErrorCategory.FATAL_HTTP,
                action=CrawlErrorAction.RAISE,
                status_code=status,
                detail_url=detail_url,
                exc=exc,
                ctx=ctx,
                external_id=external_id,
            )
            self._capture_sentry(exc, ctx=ctx, detail_url=detail_url, category=CrawlErrorCategory.FATAL_HTTP)
            return CrawlErrorHandlingResult(
                action=CrawlErrorAction.RAISE,
                category=CrawlErrorCategory.FATAL_HTTP,
                status_code=status,
            )

        self._log(
            "crawl_error",
            category=CrawlErrorCategory.UNKNOWN,
            action=CrawlErrorAction.RAISE,
            status_code=status,
            detail_url=detail_url,
            exc=exc,
            ctx=ctx,
            external_id=external_id,
            include_trace=True,
        )
        self._capture_sentry(exc, ctx=ctx, detail_url=detail_url, category=CrawlErrorCategory.UNKNOWN)
        return CrawlErrorHandlingResult(
            action=CrawlErrorAction.RAISE,
            category=CrawlErrorCategory.UNKNOWN,
            status_code=status,
        )

    def _log(
        self,
        message: str,
        *,
        category: CrawlErrorCategory,
        action: CrawlErrorAction,
        status_code: int | None,
        detail_url: str,
        exc: Exception,
        ctx: CrawlLogContext,
        external_id: str | None,
        include_trace: bool = False,
    ) -> None:
        extra = {
            **ctx.extra_for_log(),
            "error_category": category.value,
            "error_action": action.value,
            "status_code": str(status_code or ""),
            "url": detail_url[:200],
            "external_id": external_id or "",
        }
        logger.warning(
            "%s category=%s action=%s status=%s url=%s error=%s",
            message,
            category.value,
            action.value,
            status_code,
            detail_url[:200],
            exc,
            exc_info=include_trace,
            extra=extra,
        )

    def _capture_sentry(
        self,
        exc: Exception,
        *,
        ctx: CrawlLogContext,
        detail_url: str,
        category: CrawlErrorCategory,
    ) -> None:
        try:
            import sentry_sdk

            for k, v in ctx.extra_for_log().items():
                if v:
                    sentry_sdk.set_tag(k, v)
            sentry_sdk.set_tag("crawl.error_category", category.value)
            sentry_sdk.set_tag("crawl.url", detail_url[:200])
            sentry_sdk.capture_exception(exc)
        except Exception:
            logger.debug("Sentry capture failed for crawl error", exc_info=True)


def _status_code(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    if response is not None and hasattr(response, "status_code"):
        try:
            return int(response.status_code)
        except (TypeError, ValueError):
            return None
    return None

