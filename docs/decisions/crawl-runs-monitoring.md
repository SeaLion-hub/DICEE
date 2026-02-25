# crawl_runs 감시 (옵션 A: 단기 유지)

crawl_runs 테이블은 복합 PK `(id, started_at)` + RANGE(started_at) 파티셔닝을 유지한다.  
앱 계약은 "run_id(id)당 1행만 생성"이지만 DB가 이를 강제하지 않으므로, **감시 쿼리 주기 실행 + 알림**으로 이상 탐지한다.

## 감시 쿼리

```sql
SELECT id, count(*) AS cnt
FROM crawl_runs
GROUP BY id
HAVING count(*) > 1;
```

- **의미**: 동일 `id`에 대해 2행 이상 존재하는 경우만 반환.
- **정상**: 결과 0행.
- **이상**: 결과 ≥ 1행 → 알림 발송 대상.

## 주기 실행

- **방식**: Celery Beat 주기 태스크 또는 cron/스크립트.
- **권장 주기**: 1일 1회(예: 새벽) 또는 배치(close-stale-crawl-runs 등) 직후.
- **구현**: 별도 Celery task에서 위 쿼리 실행 후 행 수 확인.  
  (예: `close_stale_crawl_runs_task`와 동일 스케줄 블록에 `check_crawl_runs_id_uniqueness_task` 추가, 또는 독립 스케줄.)

## 알림 조건

- **조건**: 쿼리 결과 **행 수 ≥ 1**이면 알림 발송.
- **채널**: 슬랙·이메일·메트릭(예: Prometheus gauge) 등 팀에서 정한 채널.
- **내용**: `id`, `cnt` 목록 및 "crawl_runs id 중복 감지" 요약.

## 참고

- 옵션 B(스키마 정합화·id 단일 PK)는 별도 이슈로 관리.  
- 본 문서는 옵션 A 유지 시 운영 Runbook 일부로 사용.
