"""Spool entry metadata helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ._constants import (
    SPOOL_DEAD_LETTER_REASON_KEY,
    SPOOL_DEAD_LETTERED_AT_KEY,
    SPOOL_LAST_ERROR_AT_KEY,
    SPOOL_LAST_ERROR_MESSAGE_KEY,
    SPOOL_LAST_ERROR_MESSAGE_MAX_LEN,
    SPOOL_LAST_ERROR_STAGE_KEY,
    SPOOL_LAST_ERROR_TYPE_KEY,
    SPOOL_RETRY_COUNT_KEY,
)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_error_message(error: BaseException | str | None) -> str | None:
    if error is None:
        return None
    msg = str(error)
    if len(msg) > SPOOL_LAST_ERROR_MESSAGE_MAX_LEN:
        return msg[:SPOOL_LAST_ERROR_MESSAGE_MAX_LEN]
    return msg


def apply_error_metadata(
    entry: dict[str, Any],
    *,
    error: BaseException | str | None,
    stage: str,
    retry_count: int | None = None,
) -> dict[str, Any]:
    updated = dict(entry)
    if retry_count is not None:
        updated[SPOOL_RETRY_COUNT_KEY] = max(0, int(retry_count))

    err_type: str | None
    if isinstance(error, BaseException):
        err_type = type(error).__name__
    elif isinstance(error, str) and error:
        err_type = "Error"
    else:
        err_type = None

    updated[SPOOL_LAST_ERROR_TYPE_KEY] = err_type
    updated[SPOOL_LAST_ERROR_MESSAGE_KEY] = _safe_error_message(error)
    updated[SPOOL_LAST_ERROR_AT_KEY] = _utc_now_iso()
    updated[SPOOL_LAST_ERROR_STAGE_KEY] = stage
    return updated


def apply_dead_letter_metadata(entry: dict[str, Any], *, reason: str) -> dict[str, Any]:
    updated = dict(entry)
    updated[SPOOL_DEAD_LETTERED_AT_KEY] = _utc_now_iso()
    updated[SPOOL_DEAD_LETTER_REASON_KEY] = reason
    return updated
