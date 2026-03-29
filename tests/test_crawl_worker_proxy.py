"""crawl_worker_proxy: 설정·환경 변수 우선순위."""

from types import SimpleNamespace

import pytest
from app.core.crawl_worker_proxy import crawler_requests_proxies, get_crawler_http_proxy_url
from pydantic import SecretStr


def test_get_crawler_http_proxy_url_prefers_settings() -> None:
    s = SimpleNamespace(crawler_http_proxy_url=SecretStr("http://proxy:3128"))
    assert get_crawler_http_proxy_url(settings=s) == "http://proxy:3128"


def test_get_crawler_http_proxy_url_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRAWLER_HTTP_PROXY", "http://env-proxy:8888")
    s = SimpleNamespace(crawler_http_proxy_url=None)
    assert get_crawler_http_proxy_url(settings=s) == "http://env-proxy:8888"


def test_get_crawler_http_proxy_url_settings_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRAWLER_HTTP_PROXY", "http://env:1")
    s = SimpleNamespace(crawler_http_proxy_url=SecretStr("http://settings:2"))
    assert get_crawler_http_proxy_url(settings=s) == "http://settings:2"


def test_crawler_requests_proxies_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRAWLER_HTTP_PROXY", raising=False)
    s = SimpleNamespace(crawler_http_proxy_url=None)
    assert crawler_requests_proxies(settings=s) is None


def test_crawler_requests_proxies_dict_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRAWLER_HTTP_PROXY", raising=False)
    s = SimpleNamespace(crawler_http_proxy_url=SecretStr("http://p:8080"))
    d = crawler_requests_proxies(settings=s)
    assert d == {"http": "http://p:8080", "https": "http://p:8080"}
