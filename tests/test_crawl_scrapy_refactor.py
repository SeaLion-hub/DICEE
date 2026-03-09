"""Tests for Scrapy-style crawler refactor building blocks."""

import asyncio
from types import SimpleNamespace

import pytest
from requests import Response
from requests.exceptions import HTTPError


def _http_error(status_code: int) -> HTTPError:
    resp = Response()
    resp.status_code = status_code
    return HTTPError(str(status_code), response=resp)


def test_sync_downloader_retry_403_allowed_host_retries_once():
    from app.services.crawl.downloader_middleware import (
        DownloadRequest,
        DownloadResponse,
        SyncDownloaderMiddlewareManager,
        SyncRetryMiddleware,
    )

    calls = {"count": 0}

    def _sender(_request: DownloadRequest) -> DownloadResponse:
        calls["count"] += 1
        if calls["count"] == 1:
            raise _http_error(403)
        return DownloadResponse(url="https://example.com/detail/1", body="ok")

    manager = SyncDownloaderMiddlewareManager(
        [
            SyncRetryMiddleware(
                max_attempts=3,
                backoff_base_seconds=0.0,
                backoff_max_seconds=0.0,
                retry_403_hosts={"example.com"},
            )
        ]
    )
    out = manager.fetch(
        DownloadRequest(url="https://example.com/detail/1", timeout=1.0),
        _sender,
    )

    assert out.body == "ok"
    assert calls["count"] == 2


def test_sync_downloader_retry_403_non_allowed_host_does_not_retry():
    from app.services.crawl.downloader_middleware import (
        DownloadRequest,
        SyncDownloaderMiddlewareManager,
        SyncRetryMiddleware,
    )

    calls = {"count": 0}

    def _sender(_request: DownloadRequest):
        calls["count"] += 1
        raise _http_error(403)

    manager = SyncDownloaderMiddlewareManager(
        [
            SyncRetryMiddleware(
                max_attempts=3,
                backoff_base_seconds=0.0,
                backoff_max_seconds=0.0,
                retry_403_hosts=set(),
            )
        ]
    )

    with pytest.raises(HTTPError):
        manager.fetch(DownloadRequest(url="https://example.com/detail/1", timeout=1.0), _sender)

    assert calls["count"] == 1


def test_fetch_html_forwards_request_meta_to_middleware(monkeypatch):
    from app.core import crawl_http
    from app.services.crawl.downloader_middleware import DownloadRequest, DownloadResponse

    captured: dict[str, DownloadRequest] = {}

    class _FakeManager:
        def fetch(self, request: DownloadRequest, sender):
            captured["request"] = request
            return DownloadResponse(url=request.url, body="<html>ok</html>")

    monkeypatch.setattr(crawl_http, "get_default_sync_downloader_manager", lambda: _FakeManager())

    out = crawl_http.fetch_html(
        "https://example.com/list",
        request_meta={"retry_403": True},
    )

    assert out == "<html>ok</html>"
    assert captured["request"].meta.get("retry_403") is True


def test_default_notice_pipeline_resolves_external_id_and_marks_seen(monkeypatch):
    import uuid

    from app.domain.contracts.crawl_contracts import CrawlLogContext, NoticeDraft
    from app.services.crawl.item_pipeline import DefaultNoticeItemPipeline, RawNoticeItem
    from app.services.crawlers.base import ScrapeResult

    captured: dict[str, str | None] = {"external_id": None}

    def _fake_build(
        college_id,
        post,
        detail_url,
        title,
        date_str,
        html_content,
        images,
        attachments,
        body_text_for_hash=None,
        external_id=None,
        ctx=None,
    ):
        captured["external_id"] = external_id
        return NoticeDraft(
            college_id=college_id,
            external_id=external_id or "",
            title=title,
            url=detail_url,
            content_url=None,
            images=[],
            attachments=[],
            content_hash="hash",
            published_at=None,
        )

    monkeypatch.setattr("app.services.crawl.item_pipeline.build_notice_payload", _fake_build)

    seen: set[str] = set()

    class _SeenAdapter:
        def __init__(self, backing: set[str]) -> None:
            self._backing = backing

        def add(self, x: str) -> None:
            self._backing.add(x)

        def __contains__(self, x: str) -> bool:  # type: ignore[override]
            return x in self._backing

    pipeline = DefaultNoticeItemPipeline(_SeenAdapter(seen))
    college_id = uuid.uuid4()
    item = RawNoticeItem(
        college_id=college_id,
        post={"url": "https://example.com/view?articleNo=42"},
        detail_url="https://example.com/view?articleNo=42",
        data=ScrapeResult("Title", "2024.01.01", "<p>Body</p>", [], []),
    )

    out = pipeline.process(item, CrawlLogContext(college_code="engineering"))

    assert out is not None
    assert out.external_id == "42"
    assert captured["external_id"] == "42"
    assert "42" in seen

    duplicate = pipeline.process(item, CrawlLogContext(college_code="engineering"))
    assert duplicate is None


def test_crawl_error_handler_classifies_404_and_parser():
    from app.core.metrics import DROP_REASON_SKIPPABLE_HTTP
    from app.domain.contracts.crawl_contracts import CrawlLogContext
    from app.services.crawl.error_handling import (
        CrawlErrorAction,
        CrawlErrorCategory,
        CrawlErrorHandler,
    )

    handler = CrawlErrorHandler()
    ctx = CrawlLogContext(college_code="engineering")

    drop = handler.handle(_http_error(404), detail_url="https://example.com/404", ctx=ctx)
    assert drop.action == CrawlErrorAction.DROP
    assert drop.category == CrawlErrorCategory.HTTP_404
    assert drop.drop_reason == DROP_REASON_SKIPPABLE_HTTP

    parser = handler.handle(ValueError("selector changed"), detail_url="https://example.com/p", ctx=ctx)
    assert parser.action == CrawlErrorAction.PARSER
    assert parser.category == CrawlErrorCategory.SELECTOR_ERROR


def test_celery_dispatcher_applies_memory_backpressure(monkeypatch):
    from app.adapters import celery_crawl_dispatcher as dispatcher_module

    monkeypatch.setattr(dispatcher_module.settings, "celery_dispatch_memory_soft_limit_mb", 1000)
    monkeypatch.setattr(dispatcher_module.settings, "celery_dispatch_backpressure_step_seconds", 30)
    monkeypatch.setattr(dispatcher_module.settings, "celery_dispatch_backpressure_max_seconds", 300)
    monkeypatch.setattr(
        dispatcher_module,
        "_collect_resource_snapshot",
        lambda: dispatcher_module._ResourceSnapshot(memory_mb=2400.0, net_sent_mb=10.0, net_recv_mb=20.0),
    )

    captured: dict[str, int] = {}

    def _apply_async(*args, **kwargs):
        captured["countdown"] = int(kwargs.get("countdown") or 0)
        return SimpleNamespace(id="task-123")

    monkeypatch.setattr("app.services.tasks.crawl_college_task.apply_async", _apply_async)

    task_id = asyncio.run(
        dispatcher_module.CeleryCrawlDispatcher().enqueue(
            college_code="engineering",
            lock_token="token",
            countdown=10,
            enqueued_at=1.0,
        )
    )

    assert task_id == "task-123"
    assert captured["countdown"] > 10


def test_celery_dispatcher_snapshot_fail_open_keeps_original_countdown(monkeypatch):
    from app.adapters import celery_crawl_dispatcher as dispatcher_module

    monkeypatch.setattr(
        dispatcher_module,
        "_collect_resource_snapshot",
        lambda: dispatcher_module._ResourceSnapshot(memory_mb=None, net_sent_mb=None, net_recv_mb=None),
    )

    captured: dict[str, int] = {}

    def _apply_async(*args, **kwargs):
        captured["countdown"] = int(kwargs.get("countdown") or 0)
        return SimpleNamespace(id="task-456")

    monkeypatch.setattr("app.services.tasks.crawl_college_task.apply_async", _apply_async)

    task_id = asyncio.run(
        dispatcher_module.CeleryCrawlDispatcher().enqueue(
            college_code="engineering",
            lock_token=None,
            countdown=7,
            enqueued_at=1.0,
        )
    )

    assert task_id == "task-456"
    assert captured["countdown"] == 7


def test_base_crawler_scaffold_exports_legacy_callables(monkeypatch):
    from app.services.crawlers import base as base_module

    class _DemoCrawler(base_module.BaseCrawler):
        college_code = "demo"
        display_name = "Demo College"
        start_urls = ("https://demo.example/list",)

        def parse_links(self, html: str, list_url: str) -> list[base_module.LinkItem]:
            assert "list" in html
            assert list_url == "https://demo.example/list"
            return [{"url": "https://demo.example/detail/1", "no": "1"}]

        def parse_detail(self, html: str, url: str):
            return base_module.ScrapeResult(
                title="Demo",
                date_str="2024.01.01",
                html_content=html,
                images=[],
                attachments=[],
            )

    monkeypatch.setattr(base_module, "fetch_html", lambda *args, **kwargs: "<div>list</div>")
    monkeypatch.setattr(base_module, "fetch_html_detail_cached", lambda *args, **kwargs: "<div>detail</div>")

    crawler = _DemoCrawler()
    links = crawler.get_links("")
    detail = crawler.scrape_detail("https://demo.example/detail/1")
    get_links_fn, scrape_detail_fn = crawler.legacy_exports()
    spec = crawler.to_crawler_spec(get_links_name="get_notice_links", scrape_detail_name="scrape_detail")

    assert links[0].get("no") == "1"
    assert scrape_detail_fn("https://demo.example/detail/1").html_content == "<div>detail</div>"
    assert get_links_fn("")[0]["url"] == "https://demo.example/detail/1"
    assert detail.title == "Demo"
    assert spec.college_code == "demo"
    assert spec.get_links == "get_notice_links"
    assert spec.scrape_detail == "scrape_detail"

