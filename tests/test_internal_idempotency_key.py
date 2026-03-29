"""internal_crawl_service.normalize_trigger_idempotency_key 단위 테스트."""

from app.services.internal_crawl_service import normalize_trigger_idempotency_key


def test_normalize_trigger_idempotency_key_none_and_empty() -> None:
    assert normalize_trigger_idempotency_key(None) is None
    assert normalize_trigger_idempotency_key("") is None
    assert normalize_trigger_idempotency_key("   ") is None


def test_normalize_trigger_idempotency_key_strips() -> None:
    assert normalize_trigger_idempotency_key("  abc  ") == "abc"


def test_normalize_trigger_idempotency_key_whitespace_only_becomes_none() -> None:
    assert normalize_trigger_idempotency_key("\t\n") is None
