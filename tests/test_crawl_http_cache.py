"""Crawl detail page read-through cache (fetch_html_detail_cached) 검증."""

from unittest.mock import MagicMock, patch

from app.core.crawl_http import fetch_html_detail_cached


def test_fetch_html_detail_cached_disabled_falls_back_to_fetch_html():
    """캐시 비활성화 시 fetch_html 호출 (fail-open)."""
    with patch("app.core.crawl_http.settings") as mock_settings:
        mock_settings.crawl_detail_cache_enabled = False
        with patch("app.core.crawl_http.get_shared_sync_redis_client", return_value=None):
            with patch("app.core.crawl_http.fetch_html", return_value="<html>ok</html>") as mock_fetch:
                out = fetch_html_detail_cached("https://example.com/detail/1", timeout=1)
                assert out == "<html>ok</html>"
                mock_fetch.assert_called_once()


def test_fetch_html_detail_cached_redis_none_fail_open():
    """Redis client None 시 fetch_html 호출 (fail-open)."""
    with patch("app.core.crawl_http.settings") as mock_settings:
        mock_settings.crawl_detail_cache_enabled = True
        mock_settings.crawl_detail_cache_ttl_seconds = 300
        mock_settings.crawl_detail_cache_key_prefix = "dicee:crawl:detail:"
        with patch("app.core.crawl_http.get_shared_sync_redis_client", return_value=None):
            with patch("app.core.crawl_http.fetch_html", return_value="<html>ok</html>") as mock_fetch:
                out = fetch_html_detail_cached("https://example.com/detail/2", timeout=1)
                assert out == "<html>ok</html>"
                mock_fetch.assert_called_once()


def test_fetch_html_detail_cached_hit_does_not_call_fetch_html():
    """캐시 hit 시 실제 HTTP(fetch_html) 미호출."""
    with patch("app.core.crawl_http.settings") as mock_settings:
        mock_settings.crawl_detail_cache_enabled = True
        mock_settings.crawl_detail_cache_ttl_seconds = 300
        mock_settings.crawl_detail_cache_key_prefix = "dicee:crawl:detail:"
        mock_client = MagicMock()
        mock_client.get = MagicMock(return_value="<html>cached</html>")
        with patch("app.core.crawl_http.get_shared_sync_redis_client", return_value=mock_client):
            with patch("app.core.crawl_http.fetch_html") as mock_fetch:
                out = fetch_html_detail_cached("https://example.com/detail/3", timeout=1)
                assert out == "<html>cached</html>"
                mock_fetch.assert_not_called()


def test_fetch_html_detail_cached_miss_then_setex():
    """캐시 miss 시 fetch 후 setex 호출."""
    with patch("app.core.crawl_http.settings") as mock_settings:
        mock_settings.crawl_detail_cache_enabled = True
        mock_settings.crawl_detail_cache_ttl_seconds = 300
        mock_settings.crawl_detail_cache_key_prefix = "dicee:crawl:detail:"
        mock_client = MagicMock()
        mock_client.get = MagicMock(return_value=None)
        mock_client.setex = MagicMock()
        with patch("app.core.crawl_http.get_shared_sync_redis_client", return_value=mock_client):
            with patch("app.core.crawl_http.fetch_html", return_value="<html>fresh</html>"):
                out = fetch_html_detail_cached("https://example.com/detail/4", timeout=1)
                assert out == "<html>fresh</html>"
                mock_client.setex.assert_called_once()
                call_args = mock_client.setex.call_args[0]
                assert call_args[2] == "<html>fresh</html>"
                assert call_args[1] == 300


def test_fetch_html_detail_cached_redis_get_exception_fail_open():
    """Redis get 예외 시 fetch_html 호출 (fail-open)."""
    with patch("app.core.crawl_http.settings") as mock_settings:
        mock_settings.crawl_detail_cache_enabled = True
        mock_settings.crawl_detail_cache_ttl_seconds = 300
        mock_settings.crawl_detail_cache_key_prefix = "dicee:crawl:detail:"
        mock_client = MagicMock()
        mock_client.get = MagicMock(side_effect=ConnectionError("redis down"))
        with patch("app.core.crawl_http.get_shared_sync_redis_client", return_value=mock_client):
            with patch("app.core.crawl_http.fetch_html", return_value="<html>ok</html>") as mock_fetch:
                out = fetch_html_detail_cached("https://example.com/detail/5", timeout=1)
                assert out == "<html>ok</html>"
                mock_fetch.assert_called_once()
