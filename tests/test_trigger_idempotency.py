"""Trigger-crawl Idempotency-Key 동작 검증."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.core.redis import (
    IDEMPOTENCY_VALUE_IN_PROGRESS,
    get_trigger_idempotency_result,
    set_trigger_idempotency_result,
    try_claim_trigger_idempotency,
)


def test_try_claim_trigger_idempotency_atomic():
    """동일 키로 첫 요청만 점유 성공, 두 번째는 실패(원자적 처리)."""
    stored = {}

    class MockRedis:
        async def set(self, key, value, nx=False, ex=None):
            if nx and key in stored:
                return False
            stored[key] = value
            return True

    client = MockRedis()
    ok1 = asyncio.run(try_claim_trigger_idempotency(client, "idem-key-1", "all"))
    assert ok1 is True
    assert any(
        k.startswith("dicee:trigger_idempotency:idem-key-1:") and stored[k] == IDEMPOTENCY_VALUE_IN_PROGRESS
        for k in stored
    )

    ok2 = asyncio.run(try_claim_trigger_idempotency(client, "idem-key-1", "all"))
    assert ok2 is False


def test_get_set_trigger_idempotency_result_roundtrip():
    """Idempotency 결과 저장 후 조회 시 동일 dict 반환."""
    stored = {}

    class MockRedis:
        async def get(self, key):
            return stored.get(key)

        async def set(self, key, value, ex=None):
            stored[key] = value
            return True

    client = MockRedis()
    payload = {"enqueued": 2, "tasks": [{"college_code": "engineering", "task_id": "t1"}]}
    asyncio.run(set_trigger_idempotency_result(client, "key-1", "engineering", payload))
    assert any(k.startswith("dicee:trigger_idempotency:key-1:") for k in stored)
    out = asyncio.run(get_trigger_idempotency_result(client, "key-1", "engineering"))
    assert out == payload
