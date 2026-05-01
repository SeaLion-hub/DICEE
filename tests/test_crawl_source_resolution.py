"""crawl.source_resolution branch coverage."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from app.services.crawl import source_resolution


def _college() -> MagicMock:
    college = MagicMock()
    college.external_id = "engineering"
    return college


def _source(*, crawler_engine_key: str | None, list_url: str | None) -> MagicMock:
    src = MagicMock()
    src.crawler_engine_key = crawler_engine_key
    src.list_url = list_url
    return src


def test_resolve_crawl_module_list_url_missing_college_raises() -> None:
    with patch.object(source_resolution, "get_college_by_external_id_sync", return_value=None):
        with pytest.raises(ValueError, match="College not found"):
            source_resolution.resolve_crawl_module_list_url_and_source_sync(MagicMock(), "missing")


def test_resolve_crawl_module_list_url_uses_valid_source_engine_key() -> None:
    college = _college()
    src = _source(crawler_engine_key="custom_module", list_url=" https://source.example/list ")

    with (
        patch.object(source_resolution, "get_college_by_external_id_sync", return_value=college),
        patch.object(source_resolution, "ensure_primary_college_source_sync", return_value=src),
        patch.object(source_resolution, "CRAWLER_CONFIG", {"custom_module": {"url": "https://registry/list"}}),
    ):
        out = source_resolution.resolve_crawl_module_list_url_and_source_sync(MagicMock(), "engineering")

    assert out == (college, src, "custom_module", "https://source.example/list")


def test_resolve_crawl_module_list_url_falls_back_to_registry_module_and_url() -> None:
    college = _college()
    src = _source(crawler_engine_key="unknown_module", list_url="   ")

    with (
        patch.object(source_resolution, "get_college_by_external_id_sync", return_value=college),
        patch.object(source_resolution, "ensure_primary_college_source_sync", return_value=src),
        patch.object(source_resolution, "COLLEGE_CODE_TO_MODULE", {"engineering": "registry_module"}),
        patch.object(source_resolution, "CRAWLER_CONFIG", {"registry_module": {"url": "https://registry/list"}}),
    ):
        out = source_resolution.resolve_crawl_module_list_url_and_source_sync(MagicMock(), "engineering")

    assert out == (college, src, "registry_module", "https://registry/list")


def test_resolve_crawl_module_list_url_without_fallback_raises() -> None:
    college = _college()
    src = _source(crawler_engine_key="", list_url="https://source/list")

    with (
        patch.object(source_resolution, "get_college_by_external_id_sync", return_value=college),
        patch.object(source_resolution, "ensure_primary_college_source_sync", return_value=src),
        patch.object(source_resolution, "COLLEGE_CODE_TO_MODULE", {}),
        patch.object(source_resolution, "CRAWLER_CONFIG", {}),
    ):
        with pytest.raises(ValueError, match="No crawler module"):
            source_resolution.resolve_crawl_module_list_url_and_source_sync(MagicMock(), "engineering")


def test_resolve_crawl_module_list_url_without_any_url_raises() -> None:
    college = _college()
    src = _source(crawler_engine_key="registry_module", list_url="")

    with (
        patch.object(source_resolution, "get_college_by_external_id_sync", return_value=college),
        patch.object(source_resolution, "ensure_primary_college_source_sync", return_value=src),
        patch.object(source_resolution, "CRAWLER_CONFIG", {"registry_module": {"url": ""}}),
    ):
        with pytest.raises(ValueError, match="No list url"):
            source_resolution.resolve_crawl_module_list_url_and_source_sync(MagicMock(), "engineering")


def test_get_crawler_callables_for_college_uses_resolved_module() -> None:
    college = _college()
    src = _source(crawler_engine_key="registry_module", list_url="https://source/list")
    get_links = MagicMock(name="get_links")
    scrape = MagicMock(name="scrape")

    with (
        patch.object(
            source_resolution,
            "resolve_crawl_module_list_url_and_source_sync",
            return_value=(college, src, "registry_module", "https://source/list"),
        ) as resolve,
        patch.object(source_resolution, "get_crawler", return_value=(get_links, scrape)) as get_crawler,
    ):
        out = source_resolution.get_crawler_callables_for_college_sync(MagicMock(), "engineering")

    assert out == (get_links, scrape, "https://source/list", college, src)
    resolve.assert_called_once()
    get_crawler.assert_called_once_with("registry_module")
