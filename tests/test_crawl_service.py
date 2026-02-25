"""run_crawl_job_sync 등 크롤 서비스 단위 테스트."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from app.core.constants import CrawlRunStatus


def test_run_crawl_job_sync_rollback_then_failed_on_commit_failure():
    """
    크롤 성공 후 session.commit() 실패 시 except 진입 → rollback → 별도 세션으로 FAILED 기록 → 예외 재발생.
    PendingRollbackError 방지 및 FAILED 기록은 새 세션/트랜잭션으로 분리되는 경로 검증.
    """
    from contextlib import contextmanager

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
        return None

    session.commit.side_effect = commit_side_effect

    fail_session = MagicMock()

    @contextmanager
    def mock_get_sync_session():
        yield fail_session

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
    ) as mock_update, patch(
        "app.services.crawl_service.get_sync_session",
        side_effect=mock_get_sync_session,
    ):
        with pytest.raises(RuntimeError, match="simulated DB error"):
            run_crawl_job_sync(
                session,
                "engineering",
                "task-123",
                on_chunk_processed=lambda ids: None,
            )

        # 실패한 트랜잭션 초기화
        session.rollback.assert_called()
        # FAILED 기록은 별도 세션(fail_session)으로 1회 호출
        failed_calls = [
            c
            for c in mock_update.call_args_list
            if c.kwargs.get("status") == CrawlRunStatus.FAILED.value
        ]
        assert len(failed_calls) == 1
        assert failed_calls[0].kwargs.get("error_message", "")[:50] == (
            "simulated DB error on success-path commit"[:50]
        )
        assert failed_calls[0].args[0] is fail_session
        fail_session.commit.assert_called_once()


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
