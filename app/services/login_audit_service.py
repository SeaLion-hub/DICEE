"""Login audit enqueue helpers.

The request path should not wait for audit-table writes. It enqueues a small JSON
payload to Celery and lets the worker batch inserts.
"""

from __future__ import annotations

import logging
import uuid

from app.core.metrics import LOGIN_AUDIT_ENQUEUE_FAILED_TOTAL, increment

logger = logging.getLogger(__name__)


def enqueue_login_audit_event(
    *,
    ip_hmac: str,
    ip_hmac_key_version: str,
    user_id: uuid.UUID | None,
    provider: str | None,
) -> None:
    """Enqueue one login audit event. Caller decides whether enqueue failure is fatal."""
    payload = {
        "ip_hmac": ip_hmac,
        "ip_hmac_key_version": ip_hmac_key_version,
        "user_id": str(user_id) if user_id is not None else None,
        "provider": provider,
    }
    try:
        from app.services.tasks import process_login_audit_batch_task

        process_login_audit_batch_task.apply_async(args=([payload],), queue="critical")
    except Exception as e:
        increment(LOGIN_AUDIT_ENQUEUE_FAILED_TOTAL)
        logger.warning("Login audit enqueue failed: %s", e, exc_info=True)
        raise
