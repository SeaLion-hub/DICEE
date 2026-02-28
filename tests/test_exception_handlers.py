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


async def test_sanitize_5xx_replaces_body_without_forwarding_unsafe_headers():
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse

    from app.middleware.sanitize_5xx import Sanitize5xxMiddleware

    async def _noop_app(scope, receive, send):
        return None

    middleware = Sanitize5xxMiddleware(_noop_app)
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "path": "/x",
            "raw_path": b"/x",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )

    async def _call_next(_request):
        return PlainTextResponse(
            "Traceback: sensitive",
            status_code=500,
            headers={
                "Content-Length": "999",
                "Connection": "keep-alive",
                "X-Test-Header": "ok",
            },
        )

    response = await middleware.dispatch(request, _call_next)
    body = response.body.decode("utf-8")

    assert response.status_code == 500
    assert response.headers.get("x-test-header") == "ok"
    assert response.headers.get("connection") is None
    assert response.headers.get("content-length") != "999"
    assert "Internal server error" in body
