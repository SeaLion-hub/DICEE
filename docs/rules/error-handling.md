# 에러 처리·로깅 가이드

에러 핸들링·로깅·모니터링 코드를 작성할 때 참고할 매뉴얼. 계층별 예외 변환은 `.cursor/rules/architecture.mdc`와 함께 참고.

---

## API 에러 응답 포맷

- 모든 API 에러 응답은 **동일 필드** 사용: `detail`(문자열), `code`, `request_id`(있을 때), `errors`(validation 시). 전역 핸들러는 `app/core/exception_handlers.py`의 `_error_content`·`_normalize_detail`로 통일. `HTTPException.detail`이 dict/list여도 클라이언트에는 항상 문자열 `detail`로 내려감.

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

---

## 크롤러: 재시도·타임아웃 (필수 복기)

크롤링 로직을 수정할 때 반드시 아래를 지킨다. 상세는 [CAUTIONS 6·7절](../CAUTIONS.md#6-크롤러워커-3단계) 참고.

- **타임아웃**: HTTP 요청에 **timeout** 반드시 지정(예: 10초). `requests.get`·httpx 호출에 timeout 누락 금지. 배포 직전 체크리스트 항목.
- **재시도**: 네트워크/일시 오류 시 즉시 재시도만 하지 말 것. Celery 태스크는 **지수 백오프**(retry_backoff=True, retry_backoff_max). Gemini 호출 시 429 대응 동일.
- **Polite crawling**: 요청/페이지 간 **1초 딜레이**. 여러 단과대 순차(concurrency=1 또는 순차 enqueue). IP 차단 방지.
- **Playwright**: `--no-sandbox`, `--disable-dev-shm-usage` 필수. Celery concurrency 1~2.

---

## 크롤 에러 정책 (B) — 예외 전파·임계치 중단

- **크롤러**: `get_*_links` / `get_*_links_async`·`scrape_*_detail` 실패 시 **예외 전파(raise)**. "목록이 비어 있음"과 "에러"는 구분: 정상적으로 빈 목록이면 `[]` 반환, 에러면 raise.
- **서비스 레이어**: scrape/get_links에서 올라온 **파서·구조 예외**를 수집하고, **임계치 기반** 판단 — 실패 비율(`PARSER_FAILURE_RATIO_THRESHOLD`) 또는 연속 실패 횟수(`PARSER_CONSECUTIVE_FAILURES_THRESHOLD`) 초과 시 **태스크 실패(raise)**하여 Celery가 failed로 기록·Sentry로 조기 발견.
- **네트워크/타임아웃**: 재시도 후 스킵 가능(로그 + continue). **파서/구조 예외**는 수집·비율 계산·임계치 초과 시 즉시 `CrawlThresholdExceeded` raise.

---

## 크롤 트랜잭션: 청크 단위 commit·OOM 방지

- **crawl_college_sync**에서는 **청크 단위**(UPSERT_CHUNK_SIZE)로 `upsert_notices_bulk_sync` 후 `session.commit()`·`session.expunge_all()`을 수행해 Identity Map 비우기(OOM 방지). E1 대비.
- College 단위로는 `run_crawl_job_sync`에서 crawl_run 생성/갱신용 commit·실패 시 FAILED 기록용 별도 세션 commit을 사용. 중간 예외 시 이미 커밋된 청크는 유지·해당 college만 FAILED로 기록(PendingRollbackError·상태 유실 방지).
- 트랜잭션 경계는 오케스트레이터(`run_crawl_job_sync`·`crawl_college_sync`)만 통제. crawl_service docstring 참고.
