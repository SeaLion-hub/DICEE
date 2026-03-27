import logging
from unittest.mock import patch

import structlog
from app.core.logging_context import clear_request_context, set_request_context


def test_set_request_context_binds_structlog_contextvars() -> None:
    clear_request_context()
    set_request_context(
        request_id="req-123",
        endpoint="/v1/notices",
        method="GET",
        status_code=200,
        duration_ms=12,
        event_code="EVENT_TEST",
        college_code="yonsei",
        run_id="run-1",
        task_id="task-1",
        phase="LIST",
    )
    ctx = structlog.contextvars.get_contextvars()
    assert ctx.get("request_id") == "req-123"
    assert ctx.get("endpoint") == "/v1/notices"
    assert ctx.get("method") == "GET"
    assert ctx.get("status_code") == 200
    assert ctx.get("duration_ms") == 12
    assert ctx.get("event_code") == "EVENT_TEST"
    assert ctx.get("college_code") == "yonsei"
    assert ctx.get("run_id") == "run-1"
    assert ctx.get("task_id") == "task-1"
    assert ctx.get("phase") == "LIST"


def test_clear_request_context_clears_structlog_contextvars() -> None:
    clear_request_context()
    set_request_context(request_id="req-xyz", event_code="EVENT_X")
    assert structlog.contextvars.get_contextvars().get("request_id") == "req-xyz"
    clear_request_context()
    assert structlog.contextvars.get_contextvars().get("request_id") is None
    assert structlog.contextvars.get_contextvars().get("event_code") is None


def test_get_request_context_preserves_numeric_types() -> None:
    from app.core.logging_context import get_request_context

    clear_request_context()
    set_request_context(status_code=201, duration_ms=34)
    ctx = get_request_context()
    assert isinstance(ctx.get("status_code"), int)
    assert isinstance(ctx.get("duration_ms"), int)
    assert ctx["status_code"] == 201
    assert ctx["duration_ms"] == 34


def test_clear_request_context_resets_contextvars_to_none() -> None:
    from app.core.logging_context import get_request_context

    clear_request_context()
    set_request_context(request_id="req-1", status_code=200, duration_ms=10)
    clear_request_context()
    ctx = get_request_context()
    assert ctx["request_id"] is None
    assert ctx["status_code"] is None
    assert ctx["duration_ms"] is None


def test_structlog_bind_fail_open_logs_warning_then_debug(caplog) -> None:
    clear_request_context()
    with patch("structlog.contextvars.bind_contextvars", side_effect=RuntimeError("bind failed")):
        with caplog.at_level(logging.DEBUG):
            set_request_context(request_id="req-1")
            set_request_context(request_id="req-2")
    warning_logs = [
        r
        for r in caplog.records
        if r.levelname == "WARNING" and "structlog context bind failed" in r.getMessage()
    ]
    debug_logs = [
        r
        for r in caplog.records
        if r.levelname == "DEBUG" and "structlog context bind failed again" in r.getMessage()
    ]
    assert len(warning_logs) >= 1
    assert len(debug_logs) >= 1


def test_structlog_clear_fail_open_logs_warning(caplog) -> None:
    with patch("structlog.contextvars.clear_contextvars", side_effect=RuntimeError("clear failed")):
        with caplog.at_level(logging.WARNING):
            clear_request_context()
    warning_logs = [
        r
        for r in caplog.records
        if r.levelname == "WARNING" and "structlog context clear failed once" in r.getMessage()
    ]
    assert len(warning_logs) >= 1

