# Runbook: Crawler Retry & DLQ

## 목적

크롤 태스크 재시도 정책·DLQ 유입 시 복구 절차. 재시도 소진·max_age 초과·Fatal 예외로 DLQ에 쌓인 작업을 검토·재큐 또는 스킵 결정한다.

## 트리거

- DLQ 유입률 > 1% 알럿 (30분 지속 시 [release-rollback.md](release-rollback.md) 롤백 트리거 참조)
- Celery DLQ 큐 깊이 급증
- 크롤 성공률 SLO(99.0%, 24h) 위반

## 담당

- **Data Platform**: 큐·재시도 정책·배치 운영
- **Backend**: 크롤러·셀렉터·HTTP 정책 수정

## 기본 절차

1. DLQ 큐 깊이·유입률 확인. Sentry/로그에서 실패 원인(429, 5xx, timeout, Fatal 4xx) 분류.
2. Retryable 일시 오류(429, 5xx, timeout) 다수 시: 대상 서버 상태·Rate limit, Retry-After 적용 여부 확인. 필요 시 재큐(한도 설정).
3. Fatal(4xx)·셀렉터 변경 등 영구 실패 시: 스킵 또는 데이터 수정 후 재수집 절차 수행. 반복 실패 시 크롤러/설정 수정.
4. stuck inflight 재처리 배치가 활성화된 경우: [redis-scheduler-recovery.md](redis-scheduler-recovery.md)와 연계해 장시간 실행 중 작업 복구 여부 확인.
5. 조치 후 크롤 성공률·DLQ 유입률 재확인.
