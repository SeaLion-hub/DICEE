# ADR: 크롤 호스트별 Rate Limit (Redis + Lua)

## 상태

**부분 적용.** 현재 구현은 인메모리 `HostRateLimiter`만 사용. Redis + Lua 기반 다중 워커 공유 limiter는 미구현.

## 배경

호스트(도메인)별 최소 요청 간격을 다중 워커/프로세스에서 일관되게 적용하려면 공유 저장소가 필요하다. 인메모리만 사용하면 워커 간 제한이 깨진다.

## 결정

- **Redis + Lua (목표):** "마지막 허용 시간" 조회·갱신·대기량 계산을 Lua 스크립트 한 번에 실행(원자성). GET/SET 분리 시 미세 레이스 가능하므로 Lua만 사용.
- **키:** `dicee:rate_limit:{host}`. TTL 24시간.
- **장애 정책:** Redis 미설정/실패 시 **프로세스 로컬 limiter**(인메모리)로 degrade. 완전 skip은 대상 서버 차단 리스크가 크므로 사용하지 않음.

## 참고

- [app/core/crawl_rate_limit.py](../../app/core/crawl_rate_limit.py): **현재** HostRateLimiter(인메모리)만 구현. RedisHostRateLimiterSync/Async·Lua 스크립트는 추후 구현 시 추가.
- [app/core/redis.py](../../app/core/redis.py): Trigger lock·Blocklist용 클라이언트. Rate Limit 전용 클라이언트는 Redis+Lua 구현 시 추가.
