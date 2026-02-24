"""Trigger-crawl Idempotency-Key 동작 검증."""

from unittest.mock import AsyncMock, patch

import pytest


def test_get_set_trigger_idempotency_result_roundtrip():
    """Idempotency 결과 저장 후 조회 시 동일 dict 반환."""
    import asyncio
    import json

    from app.core.redis import get_trigger_idempotency_result, set_trigger_idempotency_result

    stored = {}

    class MockRedis:
        async def get(self, key):
            return stored.get(key)

        async def set(self, key, value, ex=None):
            stored[key] = value
            return True

    payload = {"enqueued": 2, "tasks": [{"college_code": "engineering", "task_id": "t1"}]}
    asyncio.run(set_trigger_idempotency_result(MockRedis(), "key-1", payload))
    assert "dicee:trigger_idempotency:key-1" in stored
    out = asyncio.run(get_trigger_idempotency_result(MockRedis(), "key-1"))
    assert out == payload
