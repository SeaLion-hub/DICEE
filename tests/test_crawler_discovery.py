"""CRAWLER_SPEC 자동 수집(discovery) fail-fast 경로 고정."""

from unittest.mock import MagicMock, patch

import pytest
from app.core.crawler_config import CrawlerModuleSpec, _discover_crawler_specs


def _make_module(spec: CrawlerModuleSpec, has_get_links: bool = True, has_scrape_detail: bool = True):
    mod = MagicMock()
    mod.CRAWLER_SPEC = spec
    if has_get_links:
        mod.get_notice_links = lambda: []
    else:
        mod.get_notice_links = None
    if has_scrape_detail:
        mod.scrape_detail = lambda x: ()
    else:
        mod.scrape_detail = None
    return mod


def test_discovery_fails_on_duplicate_college_code():
    """중복 college_code 시 ValueError fail-fast."""
    spec_a = CrawlerModuleSpec(
        college_code="dup",
        display_name="A",
        list_url="https://example.com/a",
        get_links="get_notice_links",
        scrape_detail="scrape_detail",
    )
    spec_b = CrawlerModuleSpec(
        college_code="dup",
        display_name="B",
        list_url="https://example.com/b",
        get_links="get_notice_links",
        scrape_detail="scrape_detail",
    )
    modules_iter = iter(
        [
            (None, "mod_a", False),
            (None, "mod_b", False),
        ]
    )
    import_map = {
        "app.services.crawlers.mod_a": _make_module(spec_a),
        "app.services.crawlers.mod_b": _make_module(spec_b),
    }

    with patch("app.core.crawler_config.pkgutil.iter_modules", return_value=modules_iter):
        with patch("app.core.crawler_config.importlib.import_module", side_effect=lambda name: import_map[name]):
            with pytest.raises(ValueError, match="Duplicate college_code"):
                _discover_crawler_specs()


def test_discovery_fails_on_invalid_url_empty():
    """list_url 비어 있으면 ValueError fail-fast."""
    spec = CrawlerModuleSpec(
        college_code="x",
        display_name="X",
        list_url="",
        get_links="get_notice_links",
        scrape_detail="scrape_detail",
    )
    modules_iter = iter([(None, "mod_x", False)])
    with patch("app.core.crawler_config.pkgutil.iter_modules", return_value=modules_iter):
        with patch("app.core.crawler_config.importlib.import_module", return_value=_make_module(spec)):
            with pytest.raises(ValueError, match="list_url is empty"):
                _discover_crawler_specs()


def test_discovery_fails_on_invalid_url_no_scheme():
    """list_url에 scheme/netloc 없으면 ValueError fail-fast."""
    spec = CrawlerModuleSpec(
        college_code="x",
        display_name="X",
        list_url="not-a-valid-url",
        get_links="get_notice_links",
        scrape_detail="scrape_detail",
    )
    modules_iter = iter([(None, "mod_x", False)])
    with patch("app.core.crawler_config.pkgutil.iter_modules", return_value=modules_iter):
        with patch("app.core.crawler_config.importlib.import_module", return_value=_make_module(spec)):
            with pytest.raises(ValueError, match="invalid"):
                _discover_crawler_specs()


def test_discovery_fails_on_missing_callable():
    """스펙에 선언된 get_links/scrape_detail이 모듈에 없으면 ValueError fail-fast."""
    spec = CrawlerModuleSpec(
        college_code="x",
        display_name="X",
        list_url="https://example.com/x",
        get_links="get_notice_links",
        scrape_detail="scrape_detail",
    )
    mod = _make_module(spec, has_get_links=True, has_scrape_detail=False)
    modules_iter = iter([(None, "mod_x", False)])
    with patch("app.core.crawler_config.pkgutil.iter_modules", return_value=modules_iter):
        with patch("app.core.crawler_config.importlib.import_module", return_value=mod):
            with pytest.raises(ValueError, match="missing callable"):
                _discover_crawler_specs()
