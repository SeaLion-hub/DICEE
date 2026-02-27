"""run_crawl_job_sync 등 크롤 서비스 단위 테스트."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from app.core.constants import CrawlRunStatus


def test_run_crawl_job_sync_rollback_then_failed_on_commit_failure():
    """
    크롤 성공 후 session.commit() 실패 시 except 진입 → rollback → 동일 세션으로 FAILED 기록 시도 → 예외 재발생.
    PendingRollbackError 방지 및 FAILED 기록은 동일 세션 우선(DB 장애 시 Redis fallback은 별도 테스트).
    """
    from app.services.crawl_service import run_crawl_job_sync

    run_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    college = MagicMock()
    college.id = uuid.UUID("00000000-0000-0000-0000-000000000002")

    session = MagicMock()
    commit_call_count = [0]

    def commit_side_effect():
        commit_call_count[0] += 1
        if commit_call_count[0] == 1:
            return None  # 첫 번째 commit (create_or_update 후) 성공
        if commit_call_count[0] == 2:
            raise RuntimeError("simulated DB error on success-path commit")
        return None  # except 내 FAILED 기록 후 commit(3번째)은 성공

    session.commit.side_effect = commit_side_effect

    with patch(
        "app.services.crawl_service.get_college_by_external_id_sync",
        return_value=college,
    ), patch(
        "app.services.crawl_service.ensure_crawl_run_task_sync",
        return_value=run_id,
    ), patch(
        "app.services.crawl_service.create_or_update_crawl_run_sync",
        return_value=MagicMock(),
    ), patch(
        "app.services.crawl_service.crawl_college_sync",
        return_value=(3, []),
    ), patch(
        "app.services.crawl_service.update_crawl_run_sync",
        return_value=MagicMock(),
    ) as mock_update:
        with pytest.raises(RuntimeError, match="simulated DB error"):
            run_crawl_job_sync(
                session,
                "engineering",
                "task-123",
                on_chunk_processed=lambda ids: None,
            )

        # 실패한 트랜잭션 초기화
        session.rollback.assert_called()
        # FAILED 기록은 동일 세션(session)으로 1회 호출
        failed_calls = [
            c
            for c in mock_update.call_args_list
            if c.kwargs.get("status") == CrawlRunStatus.FAILED.value
        ]
        assert len(failed_calls) == 1
        assert failed_calls[0].kwargs.get("error_message", "")[:50] == (
            "simulated DB error on success-path commit"[:50]
        )
        assert failed_calls[0].args[0] is session
        # except 내 FAILED 기록 후 commit 호출됨
        assert session.commit.call_count >= 2


def test_crawl_college_uses_bounded_seen_set():
    """crawl_college(비동기)는 seen으로 _BoundedSeenSet 사용 (P1 OOM 회귀 방지)."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.services.crawl_service import _BoundedSeenSet, crawl_college
    from sqlalchemy.ext.asyncio import AsyncSession

    seen_captured = []

    async def _capture_seen(client, links, college_id, scrape_fn, delay, seen):
        seen_captured.append(seen)
        if False:
            yield  # async generator (0 yields)

    college_mock = MagicMock(id=uuid.UUID("00000000-0000-0000-0000-000000000001"))
    with patch(
        "app.services.crawl_service.get_college_by_external_id",
        new=AsyncMock(return_value=college_mock),
    ), patch(
        "app.services.crawl_service.get_crawler_async",
        return_value=(
            AsyncMock(return_value=[{"url": "https://example.com/1"}]),
            AsyncMock(return_value=None),
        ),
    ), patch(
        "app.services.crawl_service._collect_payloads_async",
        side_effect=_capture_seen,
    ):
        session = MagicMock(spec=AsyncSession)
        asyncio.run(crawl_college(session, "engineering"))

    assert len(seen_captured) == 1
    assert isinstance(seen_captured[0], _BoundedSeenSet)

def test_redis_seen_set_uses_shared_sync_client(monkeypatch):
    from app.services import crawl_service as crawl_module

    class _FakePipe:
        def __init__(self):
            self.ops = []

        def sadd(self, key, value):
            self.ops.append(("sadd", key, value))
            return self

        def expire(self, key, ttl):
            self.ops.append(("expire", key, ttl))
            return self

        def execute(self):
            return True

    class _FakeClient:
        def __init__(self):
            self.pipe = _FakePipe()

        def pipeline(self):
            return self.pipe

        def sismember(self, key, value):
            return True

    fake_client = _FakeClient()
    call_count = {"count": 0}

    def _shared_client():
        call_count["count"] += 1
        return fake_client

    monkeypatch.setattr(crawl_module, "get_shared_sync_redis_client", _shared_client)

    seen = crawl_module._RedisSeenSet(
        uuid.UUID("00000000-0000-0000-0000-000000000001"),
        "redis://localhost/0",
        required=True,
    )
    seen.add("id-1")
    assert "id-1" in seen
    seen.close()

    assert call_count["count"] == 1
    assert fake_client.pipe.ops


def test_record_crawl_failure_fallback_uses_shared_sync_client(monkeypatch):
    from app.services import crawl_service as crawl_module

    class _FakeClient:
        def __init__(self):
            self.calls = []

        def set(self, key, payload, ex):
            self.calls.append((key, payload, ex))

    fake_client = _FakeClient()

    monkeypatch.setattr(crawl_module.settings, "redis_url", "redis://localhost/0")
    monkeypatch.setattr(crawl_module, "get_shared_sync_redis_client", lambda: fake_client)

    crawl_module._record_crawl_failure_fallback(
        uuid.UUID("00000000-0000-0000-0000-000000000001"),
        "task-1",
        "engineering",
        "error",
    )

    assert len(fake_client.calls) == 1
    key, payload, ttl = fake_client.calls[0]
    assert key.startswith(crawl_module.CRAWL_FAILURE_REDIS_KEY_PREFIX)
    assert "engineering" in payload
    assert ttl == crawl_module.CRAWL_FAILURE_REDIS_TTL_SECONDS
