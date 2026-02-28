"""run_crawl_job_sync 등 크롤 서비스 단위 테스트."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.constants import CrawlRunStatus
from app.domain.contracts.crawl_contracts import NoticeDraft


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

    async def _capture_seen(client, links, college_id, scrape_fn, delay, *, concurrency, seen):
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


def test_crawl_college_sync_and_async_use_same_cap_helper(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from app.services import crawl_service as crawl_module

    calls: list[tuple[str, int]] = []

    def _cap_links_for_run(links_raw, college_code, max_links):
        calls.append((college_code, max_links))
        return []

    monkeypatch.setattr(crawl_module, "_cap_links_for_run", _cap_links_for_run)

    async def _get_links_async(_client, _url):
        return [{"url": "https://example.com/1"}]

    with patch(
        "app.services.crawl_service.get_college_by_external_id",
        new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
    ), patch(
        "app.services.crawl_service.get_crawler_async",
        return_value=(
            _get_links_async,
            AsyncMock(return_value=None),
        ),
    ):
        asyncio.run(crawl_module.crawl_college(MagicMock(), "engineering"))

    with patch(
        "app.services.crawl_service.get_college_by_external_id_sync",
        return_value=MagicMock(id=uuid.uuid4()),
    ), patch(
        "app.services.crawl_service.get_crawler",
        return_value=(
            lambda _url: [{"url": "https://example.com/1"}],
            lambda _url: None,
        ),
    ):
        crawl_module.crawl_college_sync(MagicMock(), "engineering")

    assert len(calls) == 2
    assert calls[0][0] == "engineering"
    assert calls[1][0] == "engineering"
    assert calls[0][1] == calls[1][1]


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
    from app.services import crawl_service as crawl_module

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
    cfg = crawl_module.CrawlRuntimeConfig(
        polite_delay_seconds=1.0,
        page_timeout_seconds=30.0,
        upsert_chunk_size=2,
        collect_sync_max_workers=5,
        collect_in_flight_limit=500,
        max_links_per_run=50000,
        collect_async_concurrency=10,
        crawl_seen_max_size=10000,
    )
    total, ids = crawl_module._run_crawl_pipeline_sync(
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


def test_run_crawl_pipeline_async_uses_chunk_size_for_flush():
    import asyncio

    from app.services import crawl_service as crawl_module

    class _Adapter:
        def __init__(self):
            self.flush_sizes: list[int] = []

        async def collect_payloads(self, **kwargs):
            college_id = kwargs["college_id"]
            for i in range(5):
                yield _make_draft(college_id, i)

        async def upsert_chunk(self, _session, chunk):
            self.flush_sizes.append(len(chunk))
            return [uuid.uuid4() for _ in chunk]

    async def _get_links_async(_client, _url):
        return [{"url": f"https://example.com/{i}"} for i in range(5)]

    adapter = _Adapter()
    cfg = crawl_module.CrawlRuntimeConfig(
        polite_delay_seconds=1.0,
        page_timeout_seconds=30.0,
        upsert_chunk_size=2,
        collect_sync_max_workers=5,
        collect_in_flight_limit=500,
        max_links_per_run=50000,
        collect_async_concurrency=10,
        crawl_seen_max_size=10000,
    )
    total = asyncio.run(
        crawl_module._run_crawl_pipeline_async(
            MagicMock(),
            college_code="engineering",
            college_id=uuid.uuid4(),
            list_url="https://example.com/list",
            get_links_async_fn=_get_links_async,
            scrape_async_fn=AsyncMock(return_value=None),
            cfg=cfg,
            adapter=adapter,
        )
    )
    assert total == 5
    assert adapter.flush_sizes == [2, 2, 1]


def test_sync_adapter_reflects_worker_and_inflight_config(monkeypatch):
    from app.services import crawl_service as crawl_module

    captured: dict[str, int] = {}

    def _fake_collect(*args, **kwargs):
        captured["max_workers"] = kwargs["max_workers"]
        captured["in_flight_limit"] = kwargs["in_flight_limit"]
        return iter(())

    monkeypatch.setattr(crawl_module, "_collect_payloads_sync", _fake_collect)
    cfg = crawl_module.CrawlRuntimeConfig(
        polite_delay_seconds=1.0,
        page_timeout_seconds=30.0,
        upsert_chunk_size=50,
        collect_sync_max_workers=7,
        collect_in_flight_limit=321,
        max_links_per_run=50000,
        collect_async_concurrency=10,
        crawl_seen_max_size=10000,
    )
    adapter = crawl_module._DefaultSyncCrawlAdapter()
    list(
        adapter.collect_payloads(
            links=[],
            college_id=uuid.uuid4(),
            scrape_fn=lambda _url: None,
            seen=set(),
            cfg=cfg,
        )
    )
    assert captured == {"max_workers": 7, "in_flight_limit": 321}


def test_async_adapter_reflects_concurrency_config(monkeypatch):
    import asyncio

    from app.services import crawl_service as crawl_module

    captured: dict[str, int] = {}

    async def _fake_collect(*args, **kwargs):
        captured["concurrency"] = kwargs["concurrency"]
        if False:
            yield _make_draft(uuid.uuid4(), 0)

    monkeypatch.setattr(crawl_module, "_collect_payloads_async", _fake_collect)
    cfg = crawl_module.CrawlRuntimeConfig(
        polite_delay_seconds=1.0,
        page_timeout_seconds=30.0,
        upsert_chunk_size=50,
        collect_sync_max_workers=5,
        collect_in_flight_limit=500,
        max_links_per_run=50000,
        collect_async_concurrency=13,
        crawl_seen_max_size=10000,
    )
    adapter = crawl_module._DefaultAsyncCrawlAdapter()

    async def _run():
        async for _ in adapter.collect_payloads(
            client=MagicMock(),
            links=[],
            college_id=uuid.uuid4(),
            scrape_async_fn=AsyncMock(return_value=None),
            seen=set(),
            cfg=cfg,
        ):
            pass

    asyncio.run(_run())
    assert captured == {"concurrency": 13}

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


def test_scrape_one_sync_returns_exception_in_tuple_on_value_error():
    """_scrape_one_sync: ValueError 발생 시 tuple의 exc에 담겨 반환된다."""
    from app.services.crawl_service import _scrape_one_sync

    post = {"url": "https://example.com/1", "no": "ext-1"}

    def scrape_raise(_url):
        raise ValueError("parser error")

    _, detail_url, data, exc = _scrape_one_sync(post, scrape_raise)
    assert detail_url == "https://example.com/1"
    assert data is None
    assert exc is not None
    assert isinstance(exc, ValueError)
    assert str(exc) == "parser error"


def test_scrape_one_sync_keyboard_interrupt_propagates():
    """_scrape_one_sync: KeyboardInterrupt 발생 시 메인 스레드에서 함수 밖으로 전파된다."""
    from app.services.crawl_service import _scrape_one_sync

    post = {"url": "https://example.com/1"}

    def scrape_raise(_url):
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        _scrape_one_sync(post, scrape_raise)


@pytest.mark.asyncio
async def test_fetch_one_async_returns_exception_in_tuple_on_exception():
    """_fetch_one_async: 일반 Exception 발생 시 tuple로 반환된다."""
    from unittest.mock import AsyncMock, MagicMock

    from app.services.crawl_service import _fetch_one_async

    post = {"url": "https://example.com/1"}
    client = MagicMock()
    rate_limiter = MagicMock()
    rate_limiter.wait_async = AsyncMock(return_value=None)
    sem = MagicMock()
    sem.__aenter__ = AsyncMock(return_value=None)
    sem.__aexit__ = AsyncMock(return_value=None)

    async def scrape_raise(_client, url):
        raise RuntimeError("fetch failed")

    _, detail_url, data, exc = await _fetch_one_async(
        client, post, scrape_raise, rate_limiter, sem
    )
    assert detail_url == "https://example.com/1"
    assert data is None
    assert exc is not None
    assert isinstance(exc, RuntimeError)
    assert str(exc) == "fetch failed"


@pytest.mark.asyncio
async def test_fetch_one_async_cancelled_error_propagates():
    """_fetch_one_async: asyncio.CancelledError가 전파된다."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from app.services.crawl_service import _fetch_one_async

    post = {"url": "https://example.com/1"}
    client = MagicMock()
    rate_limiter = MagicMock()
    rate_limiter.wait_async = AsyncMock(return_value=None)
    sem = MagicMock()
    sem.__aenter__ = AsyncMock(return_value=None)
    sem.__aexit__ = AsyncMock(return_value=None)

    async def scrape_raise(_client, url):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await _fetch_one_async(client, post, scrape_raise, rate_limiter, sem)


def test_collect_payloads_sync_applies_rate_limit_in_worker_thread(monkeypatch):
    import threading

    from app.services import crawl_service as crawl_module
    from app.services.crawlers.base import ScrapeResult

    events: list[tuple[str, str]] = []

    class _FakeLimiter:
        def wait_sync(self, host: str) -> None:
            events.append(("wait", threading.current_thread().name))

        def close(self) -> None:
            return

    monkeypatch.setattr(crawl_module, "get_host_rate_limiter_sync", lambda _delay: _FakeLimiter())

    def _scrape(_url: str):
        events.append(("scrape", threading.current_thread().name))
        return ScrapeResult("title", "2024.01.01", "<p>body</p>", [], [])

    links = [{"no": "1", "url": "https://example.com/post/1", "title": "title"}]
    payloads = list(
        crawl_module._collect_payloads_sync(
            links,
            uuid.uuid4(),
            _scrape,
            1.0,
            max_workers=1,
            in_flight_limit=1,
            seen=set(),
        )
    )

    assert len(payloads) == 1
    assert events[0][0] == "wait"
    assert events[1][0] == "scrape"
    assert events[0][1] != "MainThread"


def test_scrape_one_sync_with_sem_retries_request_exception_and_succeeds(monkeypatch):
    import threading

    from requests.exceptions import RequestException
    from tenacity import wait_none

    from app.services import crawl_service as crawl_module
    from app.services.crawlers.base import ScrapeResult

    monkeypatch.setattr(crawl_module, "_crawl_retry_wait", wait_none())
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
    _, _, data, exc = crawl_module._scrape_one_sync_with_sem(
        post,
        _scrape,
        _FakeLimiter(),
        threading.BoundedSemaphore(1),
    )
    assert exc is None
    assert data is not None
    assert calls["scrape"] == 3
    assert calls["wait"] == 3


def test_scrape_one_sync_with_sem_retries_request_exception_until_limit(monkeypatch):
    import threading

    from tenacity import wait_none

    from app.services import crawl_service as crawl_module
    from requests.exceptions import RequestException

    monkeypatch.setattr(crawl_module, "_crawl_retry_wait", wait_none())
    calls = {"scrape": 0, "wait": 0}

    class _FakeLimiter:
        def wait_sync(self, host: str) -> None:
            calls["wait"] += 1

    def _scrape(_url: str):
        calls["scrape"] += 1
        raise RequestException("network down")

    post = {"url": "https://example.com/post/1"}
    _, _, data, exc = crawl_module._scrape_one_sync_with_sem(
        post,
        _scrape,
        _FakeLimiter(),
        threading.BoundedSemaphore(1),
    )
    assert data is None
    assert isinstance(exc, RequestException)
    assert calls["scrape"] == crawl_module.CRAWL_RETRY_MAX_ATTEMPTS
    assert calls["wait"] == crawl_module.CRAWL_RETRY_MAX_ATTEMPTS
