"""IP HMAC 유틸. 명세 3.2: 평문 IP 저장 금지. DB에는 ip_hmac, ip_hmac_key_version만 저장."""

import hashlib
import hmac
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def compute_ip_hmac(ip: str) -> tuple[str, str]:
    """
    클라이언트 IP를 HMAC-SHA256으로 해시하여 (ip_hmac, ip_hmac_key_version) 반환.
    IP가 비어 있으면 빈 문자열과 버전 반환.
    """
    if not (ip or "").strip():
        return "", settings.ip_hmac_key_version
    key = settings.ip_hmac_key.get_secret_value()
    if not key:
        if (settings.environment or "").strip().lower() == "production":
            raise ValueError("IP_HMAC_KEY is required in production (set in config)")
        logger.warning("IP_HMAC_KEY not set; using empty key (not for production)")
    digest = hmac.new(
        key.encode("utf-8") if key else b"",
        ip.strip().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest, settings.ip_hmac_key_version
