from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch


def test_enqueue_login_audit_event_sends_single_event_to_celery() -> None:
    from app.services.login_audit_service import enqueue_login_audit_event

    with patch("app.services.tasks.process_login_audit_batch_task") as task:
        enqueue_login_audit_event(
            ip_hmac="a" * 64,
            ip_hmac_key_version="v1",
            user_id=uuid.UUID("00000000-0000-7000-8000-000000000001"),
            provider="google",
        )

    task.apply_async.assert_called_once()
    kwargs = task.apply_async.call_args.kwargs
    assert kwargs["queue"] == "critical"
    event = task.apply_async.call_args.kwargs["args"][0][0]
    assert event["ip_hmac"] == "a" * 64
    assert event["user_id"] == "00000000-0000-7000-8000-000000000001"


def test_process_login_audit_batch_task_bulk_inserts_valid_events_and_skips_bad() -> None:
    from app.services import tasks as tasks_module
    from app.services.tasks import process_login_audit_batch_task

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=ctx)
    ctx.__exit__ = MagicMock(return_value=False)
    good_user_id = "00000000-0000-7000-8000-000000000002"
    events = [
        {"ip_hmac": "b" * 64, "ip_hmac_key_version": "v1", "user_id": good_user_id, "provider": "google"},
        {"ip_hmac": "", "ip_hmac_key_version": "v1", "user_id": good_user_id, "provider": "google"},
        {"ip_hmac": "c" * 64, "ip_hmac_key_version": "v1", "user_id": "not-a-uuid", "provider": "google"},
    ]

    with (
        patch.object(tasks_module, "get_sync_session", return_value=ctx),
        patch.object(tasks_module, "create_login_audits_bulk_sync", return_value=1) as bulk,
    ):
        out = process_login_audit_batch_task(events)

    assert out == {"inserted": 1, "skipped": 2}
    bulk.assert_called_once()
    rows = bulk.call_args.args[1]
    assert rows[0]["user_id"] == uuid.UUID(good_user_id)
