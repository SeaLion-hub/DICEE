"""OAuth redirect_uri 정규화 회귀: httpx 파싱·IDNA·포트 canonical·이중 인코딩 방어."""

import pytest
from app.services.auth_service import AuthError, _normalize_redirect_uri


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("https://example.com/oauth", "https://example.com/oauth"),
        ("https://example.com/oauth/", "https://example.com/oauth"),
        ("HTTP://EXAMPLE.COM/OAuth/", "http://example.com/OAuth"),
        ("https://evil.com:443/foo", "https://evil.com/foo"),
        ("http://evil.com:80/bar", "http://evil.com/bar"),
        ("http://evil.com:8080/baz", "http://evil.com:8080/baz"),
        ("https://localhost/", "https://localhost/"),
        ("https://[::1]:8443/cb", "https://[::1]:8443/cb"),
        (
            "https://\u043c\u043e\u0441\u043a\u0432\u0430.ru/callback",
            "https://xn--80adxhks.ru/callback",
        ),
    ],
)
def test_normalize_redirect_uri_canonical(uri: str, expected: str) -> None:
    assert _normalize_redirect_uri(uri) == expected


@pytest.mark.parametrize(
    "uri",
    [
        "",
        "   ",
        "not-a-scheme://host/path",
        "//evil.com/callback",
        "/relative/path",
        "https://user:pass@host/callback",
        "https://host/callback?a=1",
        "https://host/callback#frag",
        "http://localhost?",
        "https://host/%252F",
        "https://host/callback%3Fx=1",
    ],
)
def test_normalize_redirect_uri_rejects(uri: str) -> None:
    with pytest.raises(AuthError):
        _normalize_redirect_uri(uri)
