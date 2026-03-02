# Celery 재시도 정책 (Retryable vs Fatal, max_retries)

## 목적

Celery 태스크에서 **어떤 예외를 재시도할지** 명시하여 영구 실패성 예외까지 재시도해 백로그가 커지는 것을 방지한다. `max_retries`를 명시해 무한 재시도·기본값 의존을 제거한다.

## Retryable (autoretry_for에 포함)

- **HTTP**: timeout, 5xx, 408, 409, 425, 429 (일시적·서버/레이트 제한)
- **네트워크**: `RequestException`, `ConnectionError`, `TimeoutError`, `OSError` (일시적 연결/타임아웃)

이들만 Celery `autoretry_for`에 넣고, 지수 백오프 + jitter로 재시도한다.

## Fatal (재시도하지 않음)

- 그 외 4xx (400, 403, 404, 410 등): 클라이언트/리소스 문제. 재시도해도 성공하지 않음.
- 검증 오류·구성 오류: 코드/설정 수정 전까지 재시도 무의미.

Fatal은 `autoretry_for`에 넣지 않는다. 태스크 실패 후 DLQ 또는 수동 검토로 이관.

## max_retries (큐별)

- **crawl_college_task** (crawl_default): `max_retries=6`. 429는 크롤 레이어에서 Retry-After 우선 적용.
- **process_notice_ai_task** (ai): `max_retries=6`, `rate_limit="10/m"` 유지.
- 큐 분리(crawl_high, backfill) 시에는 docs/reports/BENCHMARK_INSIGHTS.md §7.2 표에 따라 큐별로 다르게 설정.

재시도 소진 또는 max_age 초과 시 DLQ 이관 정책은 Runbook [crawler-retry-dlq.md](../runbooks/crawler-retry-dlq.md) 참조.
