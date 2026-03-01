# Auth 보안 개선 기준선 (2026-03-01)

## 목적

Phase 0: 변경 전/후 회귀 비교 가능하도록 테스트·정적검사 기준선 및 auth 관련 파일 요약 기록.

## 기준선 명령 및 결과

- **pytest -q**: 실행 완료 (백그라운드 완료). 기대: 통과 건수 유지.
- **mypy app**: 기존 3 errors (worker.py, exception_handlers.py, lifespan.py). Auth 관련 오류 없음.
- **ruff check app tests**: 기존 14 issues (E501, UP038, E402, I001 등). Auth 관련: auth.py docstring E501 2건.

## 변경 전 핵심 위치 (auth)

### app/services/auth_service.py

- `verify_access_token` (L206~232): `redis_blocklist_client is not None and jti`일 때만 `is_access_blocked` 호출. Redis None이면 blocklist 검사 생략 후 통과.
- `google_login` (L352~318): Login audit 실패 시 `logger.warning("Login audit failed (user_id=%s): ...", user.id, ...)` — raw user_id 로그.
- `refresh_tokens` (L267~296): `rotate_refresh_token_version`이 None이면 AuthError만 발생, 보안 이벤트/메트릭 없음.

### app/api/v1/auth.py

- `get_current_user_id` / `get_current_user_id_and_jti`: `(AuthError, ValueError)`만 catch → 401. BlocklistUnavailableError 미처리.
- `post_google_auth`: try → google_login, commit, return. except AuthServiceUnavailableError / AuthError만. 그 외 예외 시 rollback 없음.
- `post_refresh`: try → refresh_tokens, commit, return. except AuthError에서만 rollback. 그 외 예외 시 rollback 없음.

## 참고

- Phase 1~6 적용 후 동일 명령으로 회귀 확인. Auth 경로 동작은 test_auth_security_hardening.py로 고정.
- **적용 완료**: Phase 1~6 적용 완료 (WORK_LOG 2026-03-01). 현재는 이 기준선 대비 회귀 없음.
