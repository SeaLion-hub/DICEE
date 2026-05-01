"""CrawlStatsService freshness and masking behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from app.core.constants import CrawlRunStatus, IngestionAttemptStatus
from app.domain.contracts.crawl_contracts import CrawlRunRow, IngestionFreshnessRow
from app.services import crawl_stats_service as service_module
from app.services.crawl_stats_service import CrawlStatsService


class _FakeCrawlStatsPort:
    def __init__(
        self,
        *,
        runs: list[CrawlRunRow] | None = None,
        freshness: list[IngestionFreshnessRow] | None = None,
    ) -> None:
        self.fetch_recent = AsyncMock(return_value=runs or [])
        self.fetch_source_freshness = AsyncMock(return_value=freshness or [])


@pytest.mark.asyncio
async def test_get_crawl_stats_masks_run_error_message_and_calls_port_once() -> None:
    started = datetime(2026, 4, 1, 1, 2, 3, tzinfo=UTC)
    finished = datetime(2026, 4, 1, 1, 3, 3, tzinfo=UTC)
    port = _FakeCrawlStatsPort(
        runs=[
            CrawlRunRow(
                college_code="engineering",
                started_at=started,
                finished_at=finished,
                status=CrawlRunStatus.FAILED.value,
                notices_upserted=0,
                error_message="internal stack trace",
            )
        ]
    )
    session = AsyncMock()

    out = await CrawlStatsService(port).get_crawl_stats(session, limit=7)

    assert out.limit == 7
    assert len(out.runs) == 1
    assert out.runs[0].has_error is True
    assert out.runs[0].started_at == started.isoformat()
    assert out.runs[0].finished_at == finished.isoformat()
    assert not hasattr(out.runs[0], "error_message")
    port.fetch_recent.assert_awaited_once_with(session, 7)
    port.fetch_source_freshness.assert_awaited_once_with(session)


@pytest.mark.asyncio
async def test_get_crawl_stats_marks_success_fresh_and_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_module.settings, "crawl_freshness_stale_seconds", 100)
    now = datetime.now(UTC)
    port = _FakeCrawlStatsPort(
        freshness=[
            IngestionFreshnessRow(
                college_code="fresh",
                last_attempt_status=IngestionAttemptStatus.SUCCESS.value,
                last_attempt_started_at=now - timedelta(seconds=20),
                last_attempt_finished_at=now - timedelta(seconds=20),
                total_docs=10,
            ),
            IngestionFreshnessRow(
                college_code="stale",
                last_attempt_status=IngestionAttemptStatus.SUCCESS.value,
                last_attempt_started_at=now - timedelta(seconds=200),
                last_attempt_finished_at=now - timedelta(seconds=200),
                total_docs=5,
            ),
        ]
    )

    out = await CrawlStatsService(port).get_crawl_stats(AsyncMock())

    by_code = {item.college_code: item for item in out.source_freshness}
    assert by_code["fresh"].is_stale is False
    assert by_code["stale"].is_stale is True


@pytest.mark.asyncio
async def test_get_crawl_stats_marks_running_stale_by_started_at(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_module.settings, "crawl_run_stale_seconds", 60)
    now = datetime.now(UTC)
    port = _FakeCrawlStatsPort(
        freshness=[
            IngestionFreshnessRow(
                college_code="running-fresh",
                last_attempt_status=IngestionAttemptStatus.RUNNING.value,
                last_attempt_started_at=now - timedelta(seconds=10),
                last_attempt_finished_at=None,
                total_docs=None,
            ),
            IngestionFreshnessRow(
                college_code="running-stale",
                last_attempt_status=IngestionAttemptStatus.RUNNING.value,
                last_attempt_started_at=now - timedelta(seconds=120),
                last_attempt_finished_at=None,
                total_docs=None,
            ),
        ]
    )

    out = await CrawlStatsService(port).get_crawl_stats(AsyncMock())

    by_code = {item.college_code: item for item in out.source_freshness}
    assert by_code["running-fresh"].is_stale is False
    assert by_code["running-stale"].is_stale is True


@pytest.mark.asyncio
async def test_get_crawl_stats_none_status_or_started_at_is_stale() -> None:
    port = _FakeCrawlStatsPort(
        freshness=[
            IngestionFreshnessRow(
                college_code="never-run",
                last_attempt_status=None,
                last_attempt_started_at=None,
                last_attempt_finished_at=None,
                total_docs=None,
            ),
            IngestionFreshnessRow(
                college_code="running-without-start",
                last_attempt_status=IngestionAttemptStatus.RUNNING.value,
                last_attempt_started_at=None,
                last_attempt_finished_at=None,
                total_docs=None,
            ),
        ]
    )

    out = await CrawlStatsService(port).get_crawl_stats(AsyncMock())

    assert [item.is_stale for item in out.source_freshness] == [True, True]


@pytest.mark.asyncio
async def test_get_crawl_stats_handles_naive_datetime_for_freshness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_module.settings, "crawl_freshness_stale_seconds", 100)
    naive_finished = datetime.utcnow() - timedelta(seconds=10)
    port = _FakeCrawlStatsPort(
        freshness=[
            IngestionFreshnessRow(
                college_code="naive",
                last_attempt_status=IngestionAttemptStatus.SUCCESS.value,
                last_attempt_started_at=None,
                last_attempt_finished_at=naive_finished,
                total_docs=1,
            )
        ]
    )

    out = await CrawlStatsService(port).get_crawl_stats(AsyncMock())

    assert out.source_freshness[0].is_stale is False
    assert out.source_freshness[0].last_attempt_finished_at == naive_finished.isoformat()
