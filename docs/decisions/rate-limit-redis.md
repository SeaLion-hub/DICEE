# ADR: 크롤 호스트별 Rate Limit (Redis + Lua)

## 상태

**적용 완료.** 동기 크롤 경로는 `RedisHostRateLimiterSync`, 비동기 크롤 경로는 `RedisHostRateLimiterAsync`를 통해 Redis + Lua 기반 다중 워커 공유 limiter를 사용하며, Redis 미설정/장애 시 인메모리 `HostRateLimiter`로 degrade 된다.

## 배경

호스트(도메인)별 최소 요청 간격을 다중 워커/프로세스에서 일관되게 적용하려면 공유 저장소가 필요하다. 인메모리만 사용하면 워커 간 제한이 깨진다.

## 결정

- **Redis + Lua (목표):** "마지막 허용 시간" 조회·갱신·대기량 계산을 Lua 스크립트 한 번에 실행(원자성). GET/SET 분리 시 미세 레이스 가능하므로 Lua만 사용.
- **키:** `dicee:rate_limit:{host}`. TTL 24시간.
- **장애 정책:** Redis 미설정/실패 시 **프로세스 로컬 limiter**(인메모리)로 degrade. 완전 skip은 대상 서버 차단 리스크가 크므로 사용하지 않음.

## 참고

- [app/core/crawl_rate_limit.py](../../app/core/crawl_rate_limit.py): 인메모리 `HostRateLimiter` + Redis 기반 `RedisHostRateLimiterSync/Async` 구현.
- [app/core/redis.py](../../app/core/redis.py): Trigger lock·Blocklist용 클라이언트. 동일 Redis 인스턴스를 rate limit에서도 사용하며, 장애 시 in-memory fallback이 작동한다.
