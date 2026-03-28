# ADR: 5xx 응답·로그 민감정보 원천 차단

**상태**: 채택  
**배경**: 5xx 응답이나 예외 로그에 스택/예외 메시지가 누출되면 보안·프라이버시 위험이 있음. 정책/문서가 아닌 프레임워크 레벨에서 차단한다.

---

## 결정

1. **5xx 응답**: `global_exception_handler`는 항상 `{"detail": "Internal server error", "code": "INTERNAL_ERROR"}`만 반환. 내부 예외 메시지·스택을 body에 넣지 않음. 단위 테스트로 고정.
2. **이중 방어**: `Sanitize5xxMiddleware`가 5xx 응답 body에 "Traceback", "File ", 예외 메시지 등 민감 마커가 있으면 안전한 JSON으로 교체.
3. **로거**: 프로덕션에서 `ProductionExceptionFilter`가 `exc_info`를 제거하여 포매터가 traceback을 붙이지 않도록 함. (Sentry 등 별도 수집 경로는 유지.)
4. **4xx 도메인 응답**: 클라이언트에 **내부 열거**(예: 허용 `college_code` 전체 목록)나 **`str(예외)` 그대로**를 넣지 않는다. 고정 `detail` 문자열 또는 의도된 짧은 메시지만 사용하고, 구체 식별자는 서버 로그(`request_id` 등)로만 남긴다. (예: `CollegeNotFoundError` → `college_not_found_handler`, 시맨틱 검색 빈 쿼리 → `EmptySemanticQueryError` + 상수 `detail`.)

**품질 게이트**: 본 ADR 범위 변경 후 `pytest` 통과.

---

## 적용 위치

- `app/core/exception_handlers.py`: global_exception_handler, college_not_found_handler
- `app/middleware/sanitize_5xx.py`: Sanitize5xxMiddleware
- `app/core/logging_safety.py`: ProductionExceptionFilter
- `app/main.py`: lifespan에서 프로덕션 시 필터 등록
- `app/core/exceptions.py`, `app/services/internal_crawl_service.py`, `app/api/v1/notices.py`, `app/services/gemini_text_embedding.py`: 4xx·임베딩 노출 축소
