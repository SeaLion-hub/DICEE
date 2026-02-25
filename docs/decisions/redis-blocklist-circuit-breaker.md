# Redis Blocklist Circuit Breaker (ADR)

**상태**: 채택  
**배경**: Blocklist Redis 장애 시 전면 인증 거부를 피하고, Fail-open(서명만 검증 통과)을 **코드 레벨에서 격리**하기 위해 Circuit Breaker를 도입한다.

---

## 결정

- **Circuit Breaker**: Blocklist Redis 호출(`is_access_blocked`, `add_access_to_blocklist`)을 래핑한다.
- **상태**: closed → 연속 실패 N회 시 **open** → open_seconds 후 **half_open** → 성공 시 closed, 실패 시 open.
- **열림(open) 시**: `is_access_blocked`는 **False** 반환(Fail-open). `add_access_to_blocklist`는 **no-op**.
- **환경 변수**: `REDIS_BLOCKLIST_CIRCUIT_FAILURE_THRESHOLD`(기본 5), `REDIS_BLOCKLIST_CIRCUIT_OPEN_SECONDS`(기본 30), `REDIS_BLOCKLIST_CIRCUIT_HALF_OPEN_INTERVAL_SECONDS`(기본 10).

---

## 적용 위치

- `app/core/redis.py`: `BlocklistCircuitBreaker`, `is_access_blocked`/`add_access_to_blocklist`가 내부에서 원시 호출 후 성공/실패 기록.
