"""Tests for app.core.url_safety (worker fetch URL policy)."""

import pytest
from app.core.url_safety import is_safe_worker_http_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("", False),
        ("ftp://example.com/x", False),
        ("https://example.com/path", True),
        ("http://127.0.0.1/", False),
        ("http://localhost/foo", False),
        ("http://192.168.1.1/", False),
        ("http://10.0.0.1/", False),
        ("http://169.254.169.254/latest/meta-data/", False),
        ("http://[::1]/", False),
        ("https://notice.yonsei.ac.kr/file.pdf", True),
    ],
)
def test_is_safe_worker_http_url(url: str, expected: bool) -> None:
    assert is_safe_worker_http_url(url) is expected
