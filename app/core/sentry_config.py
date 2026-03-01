"""
Sentry 전송 전 스크러빙 및 fingerprint 정책.
민감 헤더/바디 제거, 동일 에러 시그니처 기반 fingerprint로 중복 이벤트 그룹화.
"""

# 전송 전 제거할 요청 헤더 키 (소문자). Cookie, Authorization 등 민감 정보.
_SENSITIVE_HEADERS = frozenset(
    {"authorization", "cookie", "x-crawl-trigger-secret", "x-api-key", "proxy-authorization"}
)


def before_send_scrub(event: dict, hint: dict) -> dict | None:
    """
    Sentry init 시 before_send로 등록. 요청 헤더/바디 스크러빙 및 표준 fingerprint 적용.
    - request.headers에서 민감 키 제거
    - request.data 본문은 [REDACTED]로 대체
    - exception 시 exc_type + message 기반 fingerprint로 그룹화(기존 fingerprint 없을 때만)
    """
    try:
        if "request" in event and isinstance(event["request"], dict):
            req = event["request"]
            if "headers" in req and isinstance(req["headers"], dict):
                req["headers"] = {
                    k: "[REDACTED]" if (k and k.lower() in _SENSITIVE_HEADERS) else v
                    for k, v in req["headers"].items()
                }
            elif "headers" in req and isinstance(req["headers"], list):
                req["headers"] = [
                    (k, "[REDACTED]" if (k and k.lower() in _SENSITIVE_HEADERS) else v)
                    for k, v in req["headers"]
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
    except Exception:
        pass
    return event
