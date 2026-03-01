"""User ID HMAC 유틸. 로깅·Sentry용 해시. 원문 user_id 노출 금지, 키 기반 HMAC + 버전 사용."""

import hashlib
import hmac
import logging
from uuid import UUID

from app.core.config import settings

logger = logging.getLogger(__name__)


def compute_user_id_hash(user_id: UUID | str) -> str:
    """
    user_id를 HMAC-SHA256으로 해시하여 로깅·Sentry용 식별자 반환.
    키가 없으면(개발) 경고 후 SHA256 해시만 반환. 프로덕션에서는 user_id_hmac_key 설정 권장.
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
    if (settings.environment or "").strip().lower() == "production":
        logger.warning("USER_ID_HMAC_KEY not set in production; user_id_hash may be weaker")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return digest
