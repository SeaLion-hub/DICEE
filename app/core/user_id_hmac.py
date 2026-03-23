"""User ID HMAC 유틸. 로깅·Sentry용 해시. 원문 user_id 노출 금지.

Settings.require_user_id_hmac_key_in_production으로 부팅 시 production(non-migrate)에서 키를 강제한다.
compute_user_id_hash는 동일 조건에서 런타임 이중 검증(fail-fast)을 수행한다.
"""

import hashlib
import hmac
import logging
from uuid import UUID

from app.core.config import settings

logger = logging.getLogger(__name__)


def compute_user_id_hash(user_id: UUID | str) -> str:
    """
    user_id를 HMAC-SHA256으로 해시하여 로깅·Sentry용 식별자 반환.

    production이고 APP_ENTRY가 migrate가 아닌데 키가 비어 있으면 ValueError(ip_hmac와 동일 정책).
    그 외(개발·migrate 등)에서는 경고 후 SHA256 단일 해시로 폴백.
    """
    raw = str(user_id).strip()
    if not raw:
        return ""
    key = (settings.user_id_hmac_key.get_secret_value() or "").strip()
    if key:
        digest = hmac.new(
            key.encode("utf-8"),
            raw.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return digest
    env = (settings.environment or "").strip().lower()
    app_entry = (settings.app_entry or "").strip().lower()
    if env == "production" and app_entry != "migrate":
        raise ValueError(
            "USER_ID_HMAC_KEY is required in production (set in config / Railway Variables). "
            "See Settings.require_user_id_hmac_key_in_production."
        )
    logger.warning("USER_ID_HMAC_KEY not set; using SHA256-only hash (not for production API/celery)")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return digest
