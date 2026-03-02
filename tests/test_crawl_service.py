"""run_crawl_job_sync 등 크롤 서비스 단위 테스트."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from app.core.constants import CrawlRunStatus
from app.domain.contracts.crawl_contracts import NoticeDraft


def test_run_crawl_job_sync_rollback_then_failed_on_commit_failure():
    """
    크롤 성공 후 session.commit() 실패 시 except 진입 → rollback → failure_publisher(컴포지트) 호출 →
    동일 세션으로 FAILED 기록 시도 → 예외 재발생.
    PendingRollbackError 방지 및 FAILED 기록은 컴포지트 핸들러(동일 세션 우선 → Redis fallback)로 수행.
    """
    from app.services.crawl.entrypoints import handle_crawl_failure_composite, run_crawl_job_sync

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
        return None  # 컴포지트 핸들러 내 FAILED 기록 후 commit(3번째)은 성공

    session.commit.side_effect = commit_side_effect

    with (
        patch(
            "app.services.crawl.failure.get_college_by_external_id_sync",
            return_value=college,
        ),
        patch(
            "app.services.crawl.failure.ensure_crawl_run_task_sync",
            return_value=run_id,
        ),
        patch(
            "app.services.crawl.failure.create_or_update_crawl_run_sync",
            return_value=MagicMock(),
        ),
        patch(
            "app.services.crawl.failure.crawl_college_sync",
            return_value=(3, []),
        ),
        patch(
            "app.services.crawl.failure.update_crawl_run_sync",
            return_value=MagicMock(),
        ) as mock_update,
    ):
        with pytest.raises(RuntimeError, match="simulated DB error"):
            run_crawl_job_sync(
                session,
                "engineering",
                "task-123",
                on_chunk_processed=lambda ids: None,
                failure_publisher=lambda ev: handle_crawl_failure_composite(session, ev),
            )

        session.rollback.assert_called()
        failed_calls = [c for c in mock_update.call_args_list if c.kwargs.get("status") == CrawlRunStatus.FAILED.value]
        assert len(failed_calls) == 1
        assert (
            failed_calls[0].kwargs.get("error_message", "")[:50] == ("simulated DB error on success-path commit"[:50])
        )
        assert failed_calls[0].args[0] is session
        assert session.commit.call_count >= 2


def test_crawl_college_sync_uses_seen_set():
    """crawl_college_sync는 seen으로 _BoundedSeenSet 또는 _RedisSeenSet 사용 (멀티 워커 중복 방지)."""
    from unittest.mock import MagicMock, patch

    from app.services.crawl.pipeline_sync import crawl_college_sync
    from app.services.crawl.runtime import _BoundedSeenSet, _RedisSeenSet

    seen_captured = []

    def _capture_seen(*args, seen=None, **kwargs):
        if seen is not None:
            seen_captured.append(seen)
        return iter(())

    with (
        patch(
            "app.services.crawl.pipeline_sync.get_college_by_external_id_sync",
            return_value=MagicMock(id=uuid.UUID("00000000-0000-0000-0000-000000000001")),
        ),
        patch(
            "app.services.crawl.pipeline_sync.get_crawler",
            return_value=(
                lambda _url: [{"url": "https://example.com/1"}],
                lambda _url: None,
            ),
        ),
        patch(
            "app.services.crawl.pipeline_sync._collect_payloads_sync",
            side_effect=_capture_seen,
        ),
    ):
        session = MagicMock()
        crawl_college_sync(session, "engineering")

    assert len(seen_captured) == 1
    assert isinstance(seen_captured[0], _BoundedSeenSet | _RedisSeenSet)


def test_crawl_college_sync_uses_cap_helper(monkeypatch):
    """crawl_college_sync는 _cap_links_for_run을 사용해 링크 수 상한 적용."""
    from unittest.mock import patch

    from app.services.crawl import pipeline_sync as crawl_pipeline_sync
    from app.services.crawl.pipeline_sync import crawl_college_sync

    calls: list[tuple[str, int]] = []

    def _cap_links_for_run(links_raw, college_code, max_links):
        calls.append((college_code, max_links))
        return []

    monkeypatch.setattr(crawl_pipeline_sync, "_cap_links_for_run", _cap_links_for_run)

    with (
        patch(
            "app.services.crawl.pipeline_sync.get_college_by_external_id_sync",
            return_value=MagicMock(id=uuid.uuid4()),
        ),
        patch(
            "app.services.crawl.pipeline_sync.get_crawler",
            return_value=(
                lambda _url: [{"url": "https://example.com/1"}],
                lambda _url: None,
            ),
        ),
    ):
        crawl_college_sync(MagicMock(), "engineering")

    assert len(calls) == 1
    assert calls[0][0] == "engineering"


def _make_draft(college_id: uuid.UUID, i: int) -> NoticeDraft:
    """테스트용 최소 NoticeDraft."""
    return NoticeDraft(
        college_id=college_id,
        external_id=f"ext-{i}",
        title="",
        url="https://example.com",
        content_url=None,
        images=None,
        attachments=[],
        content_hash="",
        published_at=None,
    )


def test_run_crawl_pipeline_sync_uses_chunk_size_for_flush():
    from app.services.crawl.pipeline_sync import _run_crawl_pipeline_sync
    from app.services.crawl.runtime import CrawlRuntimeConfig

    class _Adapter:
        def __init__(self):
            self.flush_sizes: list[int] = []

        def collect_payloads(self, **kwargs):
            college_id = kwargs["college_id"]
            for i in range(5):
                yield _make_draft(college_id, i)

        def upsert_chunk(self, _session, chunk):
            self.flush_sizes.append(len(chunk))
            return [uuid.uuid4() for _ in chunk]

    adapter = _Adapter()
    cfg = CrawlRuntimeConfig(
        polite_delay_seconds=1.0,
        page_timeout_seconds=30.0,
        upsert_chunk_size=2,
        collect_sync_max_workers=5,
        collect_in_flight_limit=500,
        max_links_per_run=50000,
        collect_async_concurrency=10,
        crawl_seen_max_size=10000,
    )
    total, ids = _run_crawl_pipeline_sync(
        MagicMock(),
        college_code="engineering",
        college_id=uuid.uuid4(),
        list_url="https://example.com/list",
        get_links_fn=lambda _url: [{"url": f"https://example.com/{i}"} for i in range(5)],
        scrape_fn=lambda _url: None,
        run_id=None,
        on_chunk_processed=None,
        cfg=cfg,
        adapter=adapter,
    )
    assert total == 5
    assert len(ids) == 5
    assert adapter.flush_sizes == [2, 2, 1]


def test_sync_adapter_reflects_worker_and_inflight_config(monkeypatch):
    from app.services.crawl import pipeline_sync as crawl_pipeline_sync
    from app.services.crawl.pipeline_sync import _DefaultSyncCrawlAdapter
    from app.services.crawl.runtime import CrawlRuntimeConfig

    captured: dict[str, int] = {}

    def _fake_collect(*args, **kwargs):
        captured["max_workers"] = kwargs["max_workers"]
        captured["in_flight_limit"] = kwargs["in_flight_limit"]
        return iter(())

    monkeypatch.setattr(crawl_pipeline_sync, "_collect_payloads_sync", _fake_collect)
    cfg = CrawlRuntimeConfig(
        polite_delay_seconds=1.0,
        page_timeout_seconds=30.0,
        upsert_chunk_size=50,
        collect_sync_max_workers=7,
        collect_in_flight_limit=321,
        max_links_per_run=50000,
        collect_async_concurrency=10,
        crawl_seen_max_size=10000,
    )
    from app.domain.contracts.crawl_contracts import CrawlLogContext

    adapter = _DefaultSyncCrawlAdapter()
    list(
        adapter.collect_payloads(
            links=[],
            college_id=uuid.uuid4(),
            scrape_fn=lambda _url: None,
            seen=set(),
            cfg=cfg,
            ctx=CrawlLogContext(college_code="test"),
        )
    )
    assert captured == {"max_workers": 7, "in_flight_limit": 321}


def test_redis_seen_set_uses_shared_sync_client(monkeypatch):
    from app.services.crawl import runtime as crawl_runtime
    from app.services.crawl.runtime import _RedisSeenSet

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

    monkeypatch.setattr(crawl_runtime, "get_shared_sync_redis_client", _shared_client)

    seen = _RedisSeenSet(
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
    from unittest.mock import MagicMock

    from app.services.crawl import failure as crawl_failure
    from app.services.crawl.failure import (
        CRAWL_FAILURE_REDIS_KEY_PREFIX,
        CRAWL_FAILURE_REDIS_TTL_SECONDS,
        _record_crawl_failure_fallback,
    )

    class _FakeClient:
        def __init__(self):
            self.calls = []

        def set(self, key, payload, ex):
            self.calls.append((key, payload, ex))

    fake_client = _FakeClient()
    mock_settings = MagicMock()
    mock_settings.redis.redis_url = "redis://localhost/0"
    monkeypatch.setattr(crawl_failure, "settings", mock_settings)
    monkeypatch.setattr(crawl_failure, "get_shared_sync_redis_client", lambda: fake_client)

    _record_crawl_failure_fallback(
        uuid.UUID("00000000-0000-0000-0000-000000000001"),
        "task-1",
        "engineering",
        "error",
    )

    assert len(fake_client.calls) == 1
    key, payload, ttl = fake_client.calls[0]
    assert key.startswith(CRAWL_FAILURE_REDIS_KEY_PREFIX)
    assert "engineering" in payload
    assert ttl == CRAWL_FAILURE_REDIS_TTL_SECONDS


def test_scrape_one_sync_returns_exception_in_tuple_on_value_error():
    """_scrape_one_sync: ValueError 발생 시 ScrapeAttemptResult.exc에 담겨 반환된다."""
    from app.services.crawl.collect_sync import _scrape_one_sync

    post = {"url": "https://example.com/1", "no": "ext-1"}

    def scrape_raise(_url):
        raise ValueError("parser error")

    result = _scrape_one_sync(post, scrape_raise)
    assert result.detail_url == "https://example.com/1"
    assert result.data is None
    assert result.exc is not None
    assert isinstance(result.exc, ValueError)
    assert str(result.exc) == "parser error"


def test_scrape_one_sync_keyboard_interrupt_propagates():
    """_scrape_one_sync: KeyboardInterrupt 발생 시 메인 스레드에서 함수 밖으로 전파된다."""
    from app.services.crawl.collect_sync import _scrape_one_sync

    post = {"url": "https://example.com/1"}

    def scrape_raise(_url):
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        _scrape_one_sync(post, scrape_raise)


def test_collect_payloads_sync_applies_rate_limit_in_worker_thread(monkeypatch):
    import threading

    from app.services.crawl import collect_sync as crawl_collect_sync
    from app.services.crawl.collect_sync import _collect_payloads_sync
    from app.services.crawlers.base import ScrapeResult

    events: list[tuple[str, str]] = []

    class _FakeLimiter:
        def wait_sync(self, host: str) -> None:
            events.append(("wait", threading.current_thread().name))

        def close(self) -> None:
            return

    monkeypatch.setattr(crawl_collect_sync, "get_host_rate_limiter_sync", lambda _delay: _FakeLimiter())

    def _scrape(_url: str):
        events.append(("scrape", threading.current_thread().name))
        return ScrapeResult("title", "2024.01.01", "<p>body</p>", [], [])

    from app.domain.contracts.crawl_contracts import CrawlLogContext

    links = [{"no": "1", "url": "https://example.com/post/1", "title": "title"}]
    payloads = list(
        _collect_payloads_sync(
            links,
            uuid.uuid4(),
            _scrape,
            1.0,
            max_workers=1,
            in_flight_limit=1,
            seen=set(),
            ctx=CrawlLogContext(college_code="test"),
        )
    )

    assert len(payloads) == 1
    assert events[0][0] == "wait"
    assert events[1][0] == "scrape"
    assert events[0][1] != "MainThread"


def test_collect_payloads_sync_pre_dedup_reduces_scrape_calls():
    """post[\"no\"] 기준 pre-dedup + in_flight: 동일 no 두 링크 시 scrape_fn 1회만 호출."""
    from app.domain.contracts.crawl_contracts import CrawlLogContext
    from app.services.crawl.collect_sync import _collect_payloads_sync
    from app.services.crawlers.base import ScrapeResult

    scrape_calls: list[str] = []

    def _scrape(url: str):
        scrape_calls.append(url)
        return ScrapeResult("t", "2024-01-01", "<p>x</p>", [], [])

    links = [
        {"no": "same-id", "url": "https://example.com/1"},
        {"no": "same-id", "url": "https://example.com/2"},
    ]
    seen: set[str] = set()
    payloads = list(
        _collect_payloads_sync(
            links,
            uuid.uuid4(),
            _scrape,
            0.0,
            max_workers=2,
            in_flight_limit=2,
            seen=seen,
            ctx=CrawlLogContext(college_code="test"),
        )
    )
    assert len(scrape_calls) == 1, "pre-dedup + in_flight: second link with same no should not be fetched"
    assert len(payloads) == 1


def test_collect_payloads_sync_pre_dedup_many_duplicates_no_recursion():
    """대량 연속 중복 시 재귀 대신 반복으로 처리해 RecursionError가 나지 않음."""
    from app.domain.contracts.crawl_contracts import CrawlLogContext
    from app.services.crawl.collect_sync import _collect_payloads_sync
    from app.services.crawlers.base import ScrapeResult

    scrape_calls: list[str] = []

    def _scrape(url: str):
        scrape_calls.append(url)
        return ScrapeResult("t", "2024-01-01", "<p>x</p>", [], [])

    n = 1500
    links = [{"no": "dup", "url": f"https://example.com/{i}"} for i in range(n)]
    seen: set[str] = {"dup"}
    payloads = list(
        _collect_payloads_sync(
            links,
            uuid.uuid4(),
            _scrape,
            0.0,
            max_workers=2,
            in_flight_limit=2,
            seen=seen,
            ctx=CrawlLogContext(college_code="test"),
        )
    )
    assert len(scrape_calls) == 0
    assert len(payloads) == 0


def test_retry_reason_from_exc_requests_timeout_is_timeout():
    """requests.exceptions.Timeout은 retry reason이 timeout으로 집계됨."""
    from app.core.metrics import RETRY_REASON_TIMEOUT
    from app.services.crawl.collect_sync import _retry_reason_from_exc
    from requests.exceptions import Timeout as RequestsTimeout

    exc = RequestsTimeout("read timed out")
    assert _retry_reason_from_exc(exc) == RETRY_REASON_TIMEOUT


def test_scrape_one_sync_with_sem_retries_request_exception_and_succeeds(monkeypatch):
    import threading

    from app.services.crawl import collect_sync as crawl_collect_sync
    from app.services.crawl.collect_sync import _scrape_one_sync_with_sem
    from app.services.crawlers.base import ScrapeResult
    from requests.exceptions import RequestException
    from tenacity import wait_none

    monkeypatch.setattr(crawl_collect_sync, "get_crawl_retry_wait", wait_none())
    calls = {"scrape": 0, "wait": 0}

    class _FakeLimiter:
        def wait_sync(self, host: str) -> None:
            calls["wait"] += 1

    def _scrape(_url: str):
        calls["scrape"] += 1
        if calls["scrape"] < 3:
            raise RequestException("transient")
        return ScrapeResult("ok", "2024.01.01", "<p>ok</p>", [], [])

    post = {"url": "https://example.com/post/1"}
    result = _scrape_one_sync_with_sem(
        post,
        _scrape,
        _FakeLimiter(),
        threading.BoundedSemaphore(1),
    )
    assert result.exc is None
    assert result.data is not None
    assert calls["scrape"] == 3
    assert calls["wait"] == 3


def test_scrape_one_sync_with_sem_retries_request_exception_until_limit(monkeypatch):
    import threading

    from app.services.crawl import collect_sync as crawl_collect_sync
    from app.services.crawl.collect_sync import _scrape_one_sync_with_sem
    from app.services.crawl.runtime import CRAWL_RETRY_MAX_ATTEMPTS
    from requests.exceptions import RequestException
    from tenacity import wait_none

    monkeypatch.setattr(crawl_collect_sync, "get_crawl_retry_wait", wait_none())
    calls = {"scrape": 0, "wait": 0}

    class _FakeLimiter:
        def wait_sync(self, host: str) -> None:
            calls["wait"] += 1

    def _scrape(_url: str):
        calls["scrape"] += 1
        raise RequestException("network down")

    post = {"url": "https://example.com/post/1"}
    result = _scrape_one_sync_with_sem(
        post,
        _scrape,
        _FakeLimiter(),
        threading.BoundedSemaphore(1),
    )
    assert result.data is None
    assert isinstance(result.exc, RequestException)
    assert calls["scrape"] == CRAWL_RETRY_MAX_ATTEMPTS
    assert calls["wait"] == CRAWL_RETRY_MAX_ATTEMPTS


def test_retry_policy_404_skippable_no_retry(monkeypatch):
    """404/410은 스킵: 0회 추가 재시도. scrape 1회만 호출 후 결과 반환."""
    import threading

    from app.services.crawl import collect_sync as crawl_collect_sync
    from app.services.crawl.collect_sync import _get_http_status_code, _scrape_one_sync_with_sem
    from requests.exceptions import HTTPError
    from tenacity import wait_none

    monkeypatch.setattr(crawl_collect_sync, "get_crawl_retry_wait", wait_none())
    calls = {"scrape": 0}

    class _FakeLimiter:
        def wait_sync(self, host: str) -> None:
            pass

    def _scrape(_url: str):
        calls["scrape"] += 1
        resp = type("R", (), {"status_code": 404})()
        raise HTTPError("404", response=resp)

    post = {"url": "https://example.com/post/1"}
    result = _scrape_one_sync_with_sem(
        post,
        _scrape,
        _FakeLimiter(),
        threading.BoundedSemaphore(1),
    )
    assert result.exc is not None
    assert _get_http_status_code(result.exc) == 404
    assert calls["scrape"] == 1


def test_retry_policy_429_retried(monkeypatch):
    """429는 재시도 대상. 지정 횟수까지 재시도 후 성공 시 결과 반환."""
    import threading

    from app.services.crawl import collect_sync as crawl_collect_sync
    from app.services.crawl.collect_sync import _scrape_one_sync_with_sem
    from app.services.crawlers.base import ScrapeResult
    from requests.exceptions import HTTPError
    from tenacity import wait_none

    monkeypatch.setattr(crawl_collect_sync, "get_crawl_retry_wait", wait_none())
    calls = {"scrape": 0}

    class _FakeLimiter:
        def wait_sync(self, host: str) -> None:
            pass

    def _scrape(_url: str):
        calls["scrape"] += 1
        if calls["scrape"] < 2:
            resp = type("R", (), {"status_code": 429})()
            raise HTTPError("429", response=resp)
        return ScrapeResult("ok", "2024.01.01", "<p>ok</p>", [], [])

    post = {"url": "https://example.com/post/1"}
    result = _scrape_one_sync_with_sem(
        post,
        _scrape,
        _FakeLimiter(),
        threading.BoundedSemaphore(1),
    )
    assert result.exc is None
    assert result.data is not None
    assert calls["scrape"] == 2


def test_process_scrape_result_parser_threshold_aborts():
    """파서 실패 임계치 초과 시 CrawlThresholdExceeded 반환(대학 단위 중단)."""
    from app.domain.contracts.crawl_contracts import CrawlLogContext
    from app.services.crawl.collect_sync import _process_scrape_result
    from app.services.crawl_policy import (
        PARSER_CONSECUTIVE_FAILURES_THRESHOLD,
        CrawlErrorTracker,
        CrawlThresholdExceeded,
    )

    college_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    ctx = CrawlLogContext(college_code="test")
    tracker = CrawlErrorTracker()
    seen = set()
    got_threshold = None

    for i in range(PARSER_CONSECUTIVE_FAILURES_THRESHOLD + 2):
        payload, raise_exc = _process_scrape_result(
            {"url": "https://example.com/1", "no": f"n{i}"},
            "https://example.com/1",
            None,
            ValueError("parse failed"),
            college_id,
            seen,
            tracker,
            ctx,
        )
        if raise_exc is not None:
            assert isinstance(raise_exc, CrawlThresholdExceeded)
            got_threshold = raise_exc
            break
    assert got_threshold is not None, "parser threshold (ratio or consecutive) must trigger CrawlThresholdExceeded"


def test_process_scrape_result_increments_threshold_metric_on_trigger(monkeypatch):
    """CrawlThresholdExceeded 반환 직전에 CRAWL_PARSE_THRESHOLD_TRIGGER_TOTAL 1회 증가."""
    from app.core.metrics import CRAWL_PARSE_THRESHOLD_TRIGGER_TOTAL
    from app.domain.contracts.crawl_contracts import CrawlLogContext
    from app.services.crawl.collect_sync import _process_scrape_result
    from app.services.crawl_policy import (
        PARSER_CONSECUTIVE_FAILURES_THRESHOLD,
        CrawlErrorTracker,
    )

    college_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    ctx = CrawlLogContext(college_code="test")
    seen = set()
    tracker = CrawlErrorTracker()
    increment_calls: list = []

    def _capture_increment(name: str, value: int = 1, labels: dict | None = None) -> None:
        increment_calls.append((name, value, labels))

    monkeypatch.setattr("app.services.crawl.collect_sync.increment", _capture_increment)
    for i in range(PARSER_CONSECUTIVE_FAILURES_THRESHOLD + 2):
        payload, raise_exc = _process_scrape_result(
            {"url": "https://example.com/1", "no": f"n{i}"},
            "https://example.com/1",
            None,
            ValueError("parse failed"),
            college_id,
            seen,
            tracker,
            ctx,
        )
        if raise_exc is not None:
            break
    threshold_increments = [c for c in increment_calls if c[0] == CRAWL_PARSE_THRESHOLD_TRIGGER_TOTAL]
    assert len(threshold_increments) == 1
    assert threshold_increments[0][1] == 1


def test_process_scrape_result_increments_drop_metric_with_reason(monkeypatch):
    """중복 드롭 시 CRAWL_DROP_TOTAL에 reason=duplicate 기록."""
    from app.core.metrics import CRAWL_DROP_TOTAL, DROP_REASON_DUPLICATE
    from app.domain.contracts.crawl_contracts import CrawlLogContext
    from app.services.crawl.collect_sync import _process_scrape_result
    from app.services.crawl_policy import CrawlErrorTracker
    from app.services.crawlers.base import ScrapeResult

    college_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    ctx = CrawlLogContext(college_code="test")
    seen: set[str] = {"already-seen"}
    tracker = CrawlErrorTracker()
    increment_calls: list = []

    def _capture_increment(name: str, value: int = 1, labels: dict | None = None) -> None:
        increment_calls.append((name, value, labels))

    monkeypatch.setattr("app.services.crawl.collect_sync.increment", _capture_increment)
    data = ScrapeResult("title", "2024-01-01", "<p>body</p>", [], [])
    payload, raise_exc = _process_scrape_result(
        {"no": "already-seen", "url": "https://example.com/1"},
        "https://example.com/1",
        data,
        None,
        college_id,
        seen,
        tracker,
        ctx,
    )
    assert payload is None
    assert raise_exc is None
    drop_duplicate = [
        c
        for c in increment_calls
        if c[0] == CRAWL_DROP_TOTAL and (c[2] or {}).get("reason") == DROP_REASON_DUPLICATE
    ]
    assert len(drop_duplicate) == 1
