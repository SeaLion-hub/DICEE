"""Worker-side HTTP URL guards. Reduces SSRF risk when fetching URLs stored from crawled content."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
        "metadata.google.internal",
        "169.254.169.254",
    }
)


def is_safe_worker_http_url(url: str) -> bool:
    """
    True if URL uses http(s) and the host is not an obvious internal/SSRF target.

    Blocks private, loopback, link-local, reserved, and multicast IP literals and
    common magic hostnames. Does not perform DNS resolution; hostnames that resolve
    to RFC1918 addresses are not blocked (allowlist or split-horizon DNS hardening is separate).
    """
    if not (url or "").strip():
        return False
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    if host in _BLOCKED_HOSTNAMES:
        return False
    if host.endswith(".local") or host.endswith(".localhost"):
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return True
    if addr.is_private or addr.is_loopback or addr.is_link_local:
        return False
    if addr.is_reserved or addr.is_multicast:
        return False
    return True
