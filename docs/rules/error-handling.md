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

## 크롤 트랜잭션: college 단위 원자성

- **crawl_college_sync** 내부에서는 **college 단위 1 commit**만 수행. 청크별 `session.commit()`·`expunge_all()`은 사용하지 않음.
- 한 college 크롤이 끝날 때 한 번만 `session.commit()`. 중간에 예외가 나면 **전체 롤백**되어 해당 college 공지 데이터가 부분만 저장되는 일이 없음.
- `run_crawl_job_sync`의 crawl_run 생성/갱신용 commit은 유지(작업 상태 기록).
