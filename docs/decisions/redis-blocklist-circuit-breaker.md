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

---

## Fail-open vs fail-closed (`REDIS_BLOCKLIST_FAIL_CLOSED`)

- **기본값 `false`(fail-open)**: Redis·회로가 열리면 blocklist를 건너뛰고 JWT 서명만으로 access를 통과시킨다. 로그아웃 직후 access가 만료 전까지 재사용될 수 있는 창이 생길 수 있다. 가용성 우선.
- **`true`(fail-closed)**: blocklist 조회가 불가하면 인증 경로가 **503** 등으로 막힐 수 있다. 로그아웃·차단 의미가 더 강하게 유지된다. 프로덕션 API는 배포 가이드에 따라 `true` 권장을 검토한다.

Circuit **open** 시 동작은 위 “열림(open) 시” 절과 합쳐서 읽는다.
