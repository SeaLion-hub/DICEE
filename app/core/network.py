"""
클라이언트 IP 추출 (X-Forwarded-For). Trusted Proxy 검증 후 헤더 파싱.
파싱 실패 시 fallback 금지, 400 Bad Request Drop (ADR: trusted-proxy-x-forwarded-for).
"""

import ipaddress
import logging
import random

from fastapi import Request

from app.core.config import settings
from app.core.metrics import (
    CLIENT_IP_RESOLUTION_TOTAL,
    INVALID_XFF_TOTAL,
    increment,
)

logger = logging.getLogger(__name__)

# X-Forwarded-For 역순 훑기: 최대 IP 개수. 초과 시 InvalidForwardedHeaderError.
_XFF_MAX_IPS = 32


class InvalidForwardedHeaderError(Exception):
    """신뢰 프록시 경유 요청에서 X-Forwarded-For 헤더 규격 이탈(파싱 실패·초과 등). 400 Drop."""

    pass


def _record_client_ip_resolution(*, mode: str, trusted_peer: bool) -> None:
    increment(
        CLIENT_IP_RESOLUTION_TOTAL,
        labels={"mode": mode, "trusted_peer": "true" if trusted_peer else "false"},
    )


def _maybe_log_resolution_sample(*, client_host: str, xff_used: bool) -> None:
    raw_rate = getattr(settings, "client_ip_resolution_log_sample_rate", 0.0)
    try:
        rate = float(raw_rate)
    except (TypeError, ValueError):
        rate = 0.0
    if rate <= 0:
        return
    if random.random() < rate:
        logger.info(
            "client_ip_resolution_sample: client_host=%s xff_used=%s",
            client_host,
            xff_used,
        )


def warn_trusted_proxy_configuration() -> None:
    """
    TRUSTED_PROXY_IPS 설정 상태를 부팅 시 경고 로그로 남긴다.
    - 비어 있으면 X-Forwarded-For 미신뢰 모드 경고
    - 잘못된 IP 형식이 있으면 경고
    """
    raw = (settings.trusted_proxy_ips or "").strip()
    if not raw:
        logger.warning(
            "TRUSTED_PROXY_IPS is empty. X-Forwarded-For will not be trusted; "
            "client IP resolution falls back to direct peer."
        )
        return
    invalid: list[str] = []
    for token in raw.split(","):
        candidate = token.strip()
        if not candidate:
            continue
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            invalid.append(candidate)
    if invalid:
        logger.warning(
            "TRUSTED_PROXY_IPS contains invalid entries (ignored by matching): %s",
            ",".join(invalid[:10]),
        )


def _is_private_ip(ip: str) -> bool:
    """
    RFC 1918 사설 대역 + IPv6 private/loopback 여부.
    파싱 실패 시 InvalidForwardedHeaderError 발생 (fallback 금지).
    """
    if not ip or not ip.strip():
        return True
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        increment(INVALID_XFF_TOTAL)
        logger.warning("Invalid IP in X-Forwarded-For: %s", ip[:32] + "..." if len(ip) > 32 else ip)
        raise InvalidForwardedHeaderError("Invalid X-Forwarded-For header format") from None
    if addr.is_private or addr.is_loopback:
        return True
    return False


def get_client_ip(request: Request) -> str | None:
    """
    클라이언트 IP. 역순 훑기: X-Forwarded-For를 오른쪽→왼쪽으로 훑어 신뢰 목록에 없는 첫 IP 채택.
    직전 피어가 trusted가 아니면 request.client.host만 사용.
    신뢰 프록시 경유 시 헤더 규격 이탈(파싱 실패·초과 등)이면 InvalidForwardedHeaderError 발생 → 400 Drop.

    보안: trusted_proxy_ips_set에는 반드시 실제 프록시/ALB IP만 포함할 것. 과도하게 넣으면
    X-Forwarded-For 스푸핑으로 Rate limit 우회·해시 충돌 유도가 가능해짐. docs/CAUTIONS.md 참고.
    """
    if not request.client:
        return None
    fallback = request.client.host
    trusted = settings.trusted_proxy_ips_set
    if request.client.host not in trusted:
        _record_client_ip_resolution(mode="fallback", trusted_peer=False)
        _maybe_log_resolution_sample(client_host=fallback, xff_used=False)
        return fallback
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded or not forwarded.strip():
        _record_client_ip_resolution(mode="fallback", trusted_peer=True)
        _maybe_log_resolution_sample(client_host=fallback, xff_used=False)
        return fallback
    parts = [p.strip() for p in forwarded.split(",") if p.strip()]
    if len(parts) > _XFF_MAX_IPS:
        increment(INVALID_XFF_TOTAL)
        logger.warning("X-Forwarded-For exceeds max IPs: %d", len(parts))
        raise InvalidForwardedHeaderError("X-Forwarded-For header exceeds allowed IP count")
    for ip in reversed(parts):
        if ip not in trusted:
            if _is_private_ip(ip):
                increment(INVALID_XFF_TOTAL)
                raise InvalidForwardedHeaderError(
                    "X-Forwarded-For private IP from untrusted position; reject to prevent rate-limit abuse."
                )
            _record_client_ip_resolution(mode="xff", trusted_peer=True)
            _maybe_log_resolution_sample(client_host=fallback, xff_used=True)
            return ip
    chosen = parts[0] if parts else fallback
    _record_client_ip_resolution(mode="xff", trusted_peer=True)
    _maybe_log_resolution_sample(client_host=fallback, xff_used=True)
    return chosen
