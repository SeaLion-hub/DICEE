"""전역 예외 핸들러·5xx 응답 정제 검증. 스택/민감정보 누출 방지."""


async def test_global_exception_handler_never_leaks_stack_or_message():
    """5xx 응답 body에 예외 메시지·Traceback이 포함되지 않음을 검증(프레임워크 레벨 원천 차단)."""
    from unittest.mock import MagicMock

    from app.core.exception_handlers import global_exception_handler

    request = MagicMock()
    request.state.request_id = None
    sensitive_message = "sensitive-internal-error-message-xyz"
    exc = ValueError(sensitive_message)

    response = await global_exception_handler(request, exc)

    assert response.status_code == 500
    body = response.body.decode("utf-8")
    data = __import__("json").loads(body)
    assert data.get("detail") == "Internal server error"
    assert data.get("code") == "INTERNAL_ERROR"
    # 민감 정보 누출 금지
    assert sensitive_message not in body
    assert "Traceback" not in body
    assert "ValueError" not in body
    assert "File " not in body
