# ADR: 5xx 응답·로그 민감정보 원천 차단

**상태**: 채택  
**배경**: 5xx 응답이나 예외 로그에 스택/예외 메시지가 누출되면 보안·프라이버시 위험이 있음. 정책/문서가 아닌 프레임워크 레벨에서 차단한다.

---

## 결정

1. **5xx 응답**: `global_exception_handler`는 항상 `{"detail": "Internal server error", "code": "INTERNAL_ERROR"}`만 반환. 내부 예외 메시지·스택을 body에 넣지 않음. 단위 테스트로 고정.
2. **이중 방어**: `Sanitize5xxMiddleware`가 5xx 응답 body에 "Traceback", "File ", 예외 메시지 등 민감 마커가 있으면 안전한 JSON으로 교체.
3. **로거**: 프로덕션에서 `ProductionExceptionFilter`가 `exc_info`를 제거하여 포매터가 traceback을 붙이지 않도록 함. (Sentry 등 별도 수집 경로는 유지.)

---

## 적용 위치

- `app/core/exception_handlers.py`: global_exception_handler
- `app/middleware/sanitize_5xx.py`: Sanitize5xxMiddleware
- `app/core/logging_safety.py`: ProductionExceptionFilter
- `app/main.py`: lifespan에서 프로덕션 시 필터 등록
