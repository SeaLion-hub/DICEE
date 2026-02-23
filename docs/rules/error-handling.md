# 에러 처리·로깅 가이드

에러 핸들링·로깅·모니터링 코드를 작성할 때 참고할 매뉴얼. 계층별 예외 변환은 `.cursor/rules/architecture.mdc`와 함께 참고.

---

## 원칙

- **비즈니스 예외** → Router 또는 전역 Exception Handler에서 `HTTPException`으로 변환. Service에서는 `HTTPException`을 raise하지 않는다.
- 그 외 예상치 못한 예외 → 500 + 로그. `except Exception` 남용 금지(데이터 무결성 깨진 채 흐름이 계속됨).
- 에러 로그·Sentry에는 **컨텍스트** 포함: `task_id`, `notice_id`, `college_id` 등. "Error"만 남기지 말 것.

---

## Sentry

- 1단계에서 Sentry DSN 세팅. 3단계에서 워커까지 확장해 에러 알림을 미리 받을 것.

---

## 조용히 넘기지 말 것

- `pass`만 하고 넘기는 예외는 핵심 데이터 훼손으로 이어질 수 있음. `_parse_published_at`, `_external_id_from_url` 등에서 pass 제거·구체 예외+로그 연결.
