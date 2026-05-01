"""internal_crawl_service: 트리거 경로 메트릭."""

from unittest.mock import MagicMock

import pytest
from app.core.metrics import (
    INTERNAL_TRIGGER_CRAWL_ENQUEUED_TOTAL,
    INTERNAL_TRIGGER_CRAWL_SKIPPED_LOCK_TOTAL,
    get_counter,
)
from app.domain.contracts.internal_contracts import TriggerCrawlCmd, TriggerCrawlResultKind
from app.services.internal_crawl_service import InternalCrawlService


@pytest.mark.asyncio
async def test_trigger_skipped_lock_increments_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_acquire(_redis: object, _code: str, *, ttl_seconds: int | None = None) -> tuple[bool, None]:
        return (False, None)

    monkeypatch.setattr(
        "app.services.internal_crawl_service.acquire_trigger_lock",
        fake_acquire,
    )

    class _NoEnqueueDispatcher:
        async def enqueue(self, *args: object, **kwargs: object) -> str:
            raise AssertionError("enqueue must not run when lock not acquired")

    labels = {"college_code": "engineering"}
    before = get_counter(INTERNAL_TRIGGER_CRAWL_SKIPPED_LOCK_TOTAL, labels)
    svc = InternalCrawlService(MagicMock(), _NoEnqueueDispatcher())
    res = await svc.trigger(TriggerCrawlCmd("engineering", None, "127.0.0.1"))
    after = get_counter(INTERNAL_TRIGGER_CRAWL_SKIPPED_LOCK_TOTAL, labels)
    assert after == before + 1
    assert res.result_kind == TriggerCrawlResultKind.success
    assert "engineering" in (res.payload.get("skipped") or [])


@pytest.mark.asyncio
async def test_trigger_enqueue_success_increments_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_acquire(_redis: object, _code: str, *, ttl_seconds: int | None = None) -> tuple[bool, str]:
        return (True, "lock-token-test")

    monkeypatch.setattr(
        "app.services.internal_crawl_service.acquire_trigger_lock",
        fake_acquire,
    )

    class _OkDispatcher:
        async def enqueue(self, *args: object, **kwargs: object) -> str:
            return "task-id-metric-test"

    labels = {"college_code": "engineering"}
    before = get_counter(INTERNAL_TRIGGER_CRAWL_ENQUEUED_TOTAL, labels)
    svc = InternalCrawlService(MagicMock(), _OkDispatcher())
    res = await svc.trigger(TriggerCrawlCmd("engineering", None, "127.0.0.1"))
    after = get_counter(INTERNAL_TRIGGER_CRAWL_ENQUEUED_TOTAL, labels)
    assert after == before + 1
    assert res.result_kind == TriggerCrawlResultKind.success
    assert res.payload.get("enqueued") == 1
