"""
Sentry 전송 전 스크러빙, fingerprint 정책, 알림 억제(Option B).
민감 헤더/바디 제거, 동일 에러 시그니처 기반 fingerprint·TTL 디듀프로 알림 폭주 감소.
"""

import time
from typing import Any

# 전송 전 제거할 요청 헤더 키 (소문자). Cookie, Authorization 등 민감 정보.
_SENSITIVE_HEADERS = frozenset(
    {"authorization", "cookie", "x-crawl-trigger-secret", "x-api-key", "proxy-authorization"}
)

# Option B: 동일 시그니처 TTL 내 1회만 전송. 로그는 유지, Sentry 알림만 억제.
_SENTRY_DEDUP_TTL_SECONDS = 60
_sentry_dedup_last_sent: dict[str, float] = {}


def _event_signature(event: dict[str, Any]) -> str | None:
    """이벤트별 시그니처. fingerprint 또는 exception type+message, 또는 message. 추론 불가 시 None(디듀프 스킵)."""
    try:
        if "fingerprint" in event and isinstance(event["fingerprint"], list):
            return "|".join(str(x) for x in event["fingerprint"][:5])
        if "exception" in event and "values" in event["exception"]:
            values = event["exception"]["values"]
            if values:
                exc = values[0]
                exc_type = exc.get("type", "Unknown")
                exc_value = (exc.get("value") or "").split("\n")[0][:200]
                return f"{exc_type}|{exc_value}"
        if "message" in event and event["message"]:
            return str(event["message"])[:200]
    except Exception:
        pass
    return None


def before_send_scrub(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """
    Sentry init 시 before_send로 등록.
    - 요청 헤더/바디 스크러빙, fingerprint 적용.
    - 동일 시그니처 TTL 내 중복 전송 억제(Option B, 알림 폭주 감소).
    """
    try:
        if "request" in event and isinstance(event["request"], dict):
            req = event["request"]
            if "headers" in req and isinstance(req["headers"], dict):
                req["headers"] = {
                    k: "[REDACTED]" if (k and k.lower() in _SENSITIVE_HEADERS) else v for k, v in req["headers"].items()
                }
            elif "headers" in req and isinstance(req["headers"], list):
                req["headers"] = [
                    (k, "[REDACTED]" if (k and k.lower() in _SENSITIVE_HEADERS) else v) for k, v in req["headers"]
                ]
            if "data" in req and req.get("data") not in (None, ""):
                req["data"] = "[REDACTED]"

        if "fingerprint" not in event and "exception" in event and "values" in event["exception"]:
            values = event["exception"]["values"]
            if values:
                exc = values[0]
                exc_type = exc.get("type", "Unknown")
                exc_value = (exc.get("value") or "").split("\n")[0][:100]
                event["fingerprint"] = [f"{exc_type}", exc_value or "error"]

        # Option B: TTL 내 동일 시그니처 재전송 억제 (시그니처 추론 가능할 때만)
        sig = _event_signature(event)
        if sig is not None:
            now = time.time()
            if sig in _sentry_dedup_last_sent and (now - _sentry_dedup_last_sent[sig]) < _SENTRY_DEDUP_TTL_SECONDS:
                return None
            _sentry_dedup_last_sent[sig] = now
    except Exception:
        pass
    return event
