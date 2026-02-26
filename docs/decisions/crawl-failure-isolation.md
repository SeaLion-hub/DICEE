# ADR: 크롤 실패 컨텍스트 격리 (DB 장애 시)

**상태**: 채택  
**배경**: `run_crawl_job_sync` 예외 시 DB에 FAILED를 기록하려 할 때, DB 장애·풀 고갈이면 별도 세션 생성도 실패해 데드락/연쇄 실패 위험이 있음. 실패 컨텍스트를 중앙에서 추적할 수 있도록 외부 저장소에 격리한다.

---

## 결정

1. **동일 세션 우선**: 예외 발생 시 `session.rollback()` 후 **동일 세션**으로 `update_crawl_run_sync(..., status=FAILED)` 시도 후 `session.commit()`. DB가 정상이면 한 세션으로 실패 상태 기록.
2. **동일 세션 실패 시 Redis 격리**: DB 기록이 실패하면(DB 장애·풀 고갈) **Redis**에 실패 컨텍스트를 기록. 키: `dicee:crawl_failure:{run_id}`, 값: JSON(run_id, task_id, college_code, error_message, recorded_at), TTL: 7일. Redis 미설정/장애 시 로그만 남기고 예외는 전파하지 않음.
3. **로그만 재raise는 최후**: Redis 기록도 실패해도 원래 예외는 그대로 재전파. Celery 태스크 실패 → DLQ 전달은 기존 동작 유지.

---

## 적용 위치

- `app/services/crawl_service.py`: `run_crawl_job_sync` except 블록, `_record_crawl_failure_fallback`.
