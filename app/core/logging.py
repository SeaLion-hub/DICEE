"""Structured logging configuration (stdlib logging + structlog).

Design goals:
- Minimal diff: keep existing `logging.getLogger(__name__)` callsites.
- Safe rollout: allow output format toggle via `LOG_FORMAT=json|pretty`.
- Preserve existing root logger filters (request context, production safety).
"""

from __future__ import annotations

import logging
import os
from typing import Literal

import structlog

_LOG_FORMAT_ENV = "LOG_FORMAT"
_LOG_FORMAT_DEFAULT: Literal["pretty", "json"] = "pretty"
_CONFIGURED_FLAG = "_dicee_structlog_configured"


def _resolve_log_format(environment: str) -> Literal["pretty", "json"]:
    raw = (os.getenv(_LOG_FORMAT_ENV, "") or "").strip().lower()
    if raw in ("json", "pretty"):
        return raw  # type: ignore[return-value]
    # Safety: default to pretty unless explicitly switched to json.
    return _LOG_FORMAT_DEFAULT


def configure_logging(*, environment: str) -> None:
    """Configure structlog + stdlib logging formatting once per process."""
    root = logging.getLogger()
    if getattr(root, _CONFIGURED_FLAG, False):
        return

    log_format = _resolve_log_format(environment)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp")
    renderer: structlog.typing.Processor
    if log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        # Avoid rich traceback locals leaking sensitive values into logs.
        renderer = structlog.dev.ConsoleRenderer(exception_formatter=structlog.dev.plain_traceback)

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        timestamper,
        # Copy selected stdlib `LogRecord` attributes (injected by Filters) into event dict.
        structlog.stdlib.ExtraAdder(
            allow={
                # Request correlation
                "request_id",
                "trace_id",
                "endpoint",
                "method",
                "status_code",
                "duration_ms",
                # Business/safety
                "user_id_hash",
                "event_code",
                "code",
                # Crawl pipeline correlation
                "college_code",
                "run_id",
                "task_id",
                "phase",
                "crawler",
                # Common structured fields used at callsites
                "ip_hmac",
                "ip_hmac_key_version",
                "chunk_size",
                "elapsed_sec",
                "total_links",
                "upserted",
                "peak_pending_drafts",
                # Escape hatch: keep non-standard fields under a single key
                "context",
            }
        ),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # stdlib logging -> structlog ProcessorFormatter.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    # Avoid duplicate handlers if something else configured root already.
    if not root.handlers:
        root.addHandler(handler)
    else:
        # Best effort: if there are existing handlers, apply our formatter to StreamHandlers only.
        for h in root.handlers:
            if isinstance(h, logging.StreamHandler):
                h.setFormatter(formatter)

    # Don't change levels aggressively. Respect existing config; default to INFO if unset.
    if root.level == logging.NOTSET:
        root.setLevel(logging.INFO)

    setattr(root, _CONFIGURED_FLAG, True)


__all__ = ["configure_logging"]
