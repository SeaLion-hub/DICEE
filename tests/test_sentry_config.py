"""Unit tests for Sentry before_send scrubbing and dedup (no SDK network)."""

from __future__ import annotations

from typing import Any

import app.core.sentry_config as sentry_config
import pytest
from app.core.sentry_config import _event_signature, before_send_scrub


@pytest.fixture(autouse=True)
def _clear_dedup_cache() -> None:
    sentry_config._sentry_dedup_last_sent.clear()
    yield
    sentry_config._sentry_dedup_last_sent.clear()


def test_event_signature_from_fingerprint() -> None:
    event: dict[str, Any] = {"fingerprint": ["a", "b", "c"]}
    assert _event_signature(event) == "a|b|c"


def test_event_signature_truncates_fingerprint() -> None:
    event: dict[str, Any] = {"fingerprint": list(range(10))}
    sig = _event_signature(event)
    assert sig == "0|1|2|3|4"


def test_event_signature_from_exception_values() -> None:
    event: dict[str, Any] = {
        "exception": {"values": [{"type": "ValueError", "value": "bad\nline2"}]},
    }
    assert _event_signature(event) == "ValueError|bad"


def test_event_signature_from_message() -> None:
    event: dict[str, Any] = {"message": "hello world"}
    assert _event_signature(event) == "hello world"


def test_event_signature_none_when_empty() -> None:
    assert _event_signature({}) is None


def test_before_send_redacts_dict_headers() -> None:
    event: dict[str, Any] = {
        "request": {
            "headers": {
                "Authorization": "secret",
                "X-Crawl-Trigger-Secret": "tok",
                "X-Api-Key": "k",
                "Cookie": "c=1",
                "Proxy-Authorization": "p",
                "X-Safe": "ok",
            }
        }
    }
    hint: dict[str, Any] = {}
    out = before_send_scrub(event, hint)
    assert out is not None
    headers = out["request"]["headers"]
    assert headers["Authorization"] == "[REDACTED]"
    assert headers["X-Crawl-Trigger-Secret"] == "[REDACTED]"
    assert headers["X-Api-Key"] == "[REDACTED]"
    assert headers["Cookie"] == "[REDACTED]"
    assert headers["Proxy-Authorization"] == "[REDACTED]"
    assert headers["X-Safe"] == "ok"


def test_before_send_redacts_list_headers() -> None:
    event: dict[str, Any] = {
        "request": {
            "headers": [
                ("Authorization", "bearer x"),
                ("X-Safe", "v"),
            ]
        }
    }
    out = before_send_scrub(event, {})
    assert out is not None
    pairs = out["request"]["headers"]
    assert pairs == [("Authorization", "[REDACTED]"), ("X-Safe", "v")]


def test_before_send_redacts_request_data() -> None:
    event: dict[str, Any] = {"request": {"data": "password=1"}}
    out = before_send_scrub(event, {})
    assert out is not None
    assert out["request"]["data"] == "[REDACTED]"


def test_before_send_adds_fingerprint_from_exception() -> None:
    event: dict[str, Any] = {
        "exception": {"values": [{"type": "RuntimeError", "value": "oops\nmore"}]},
    }
    out = before_send_scrub(event, {})
    assert out is not None
    assert out.get("fingerprint") == ["RuntimeError", "oops"]


def test_before_send_dedup_returns_none_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[float] = [1000.0, 1001.0]

    def _fake_time() -> float:
        return calls.pop(0) if calls else 2000.0

    monkeypatch.setattr(sentry_config.time, "time", _fake_time)
    event: dict[str, Any] = {"message": "same"}
    first = before_send_scrub(event.copy(), {})
    assert first is not None
    second = before_send_scrub({"message": "same"}, {})
    assert second is None


def test_before_send_dedup_allows_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sentry_config.time, "time", lambda: 0.0)
    before_send_scrub({"message": "x"}, {})
    monkeypatch.setattr(sentry_config.time, "time", lambda: float(sentry_config._SENTRY_DEDUP_TTL_SECONDS + 1))
    out = before_send_scrub({"message": "x"}, {})
    assert out is not None
