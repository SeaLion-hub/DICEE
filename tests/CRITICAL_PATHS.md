# 크리티컬 경로 (회귀 테스트 우선순위)

머지 전 CI에서 고정되는 흐름과, 버그픽스 시 같은 PR에 테스트를 추가해야 하는 영역이다.

| 영역 | 검증 위치 (예시) |
|------|------------------|
| 헬스·레디니스 | `tests/test_health.py` — `/health`, `/live`, `/ready`, `/health/worker` |
| 공개 공지 API | `tests/test_notices_public_api.py`, `tests/test_notice_public_service.py` |
| 프로필·매칭·달력(5단계) | `tests/test_v1_phase5_authenticated_api.py`(인증·라우터 계약), `tests/test_matching_service.py`, `tests/test_calendar_range_parse.py`, `tests/test_calendar_ics_build.py`, `tests/test_notice_schedule_replace_sync.py` (DB 통합 확장 시 해당 PR에 추가) |
| 인증·OAuth·보안 | `tests/test_auth_service.py`, `tests/test_auth_security_hardening.py`, `tests/integration/test_auth_google_login_upsert.py` |
| 크롤 트리거·멱등 | `tests/test_trigger_idempotency.py`, `tests/test_internal_idempotency_key.py`, `tests/test_crawl_payload.py` |
| Celery·운영 태스크 | `tests/test_tasks_and_config.py` |
| API 메타·OAuth state·프리뷰 게이트 | `tests/test_api_meta_auth_internal_preview.py` |
| 비동기 크롤 HTTP(재시도·호스트 레이트 리밋) | `tests/test_downloader_middleware_async.py` |
| AI 추출 스키마·토큰 집계·래퍼 | `tests/test_ai_types_token_usage.py`, `tests/test_extract_notice_structured_wrapper.py` |
| 표 기반 크롤러 파싱(픽스처) | `tests/test_yonsei_engineering_parse.py`, `tests/test_yonsei_chemistry_parse.py`, `tests/test_yonsei_glc_parse.py` |
| 공통 타입 헬퍼 | `tests/test_typing_helpers.py` |
| 내부 메트릭 접근 | `tests/test_internal_metrics.py` |
| 아키텍처 가드 | `tests/test_architecture_imports.py` (CI 단독 단계) |

통합 DB가 필요한 테스트는 `pytest.mark.integration`이다. 로컬에서 `pytest -m "not integration"`으로 빠른 루프를 돌릴 수 있다.
