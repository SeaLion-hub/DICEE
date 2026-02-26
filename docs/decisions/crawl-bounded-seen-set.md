# ADR: 크롤 중복 제거용 Bounded Seen Set 및 분산 Seen Set

## 상태

**적용 완료.** 동기 크롤(`crawl_college_sync`)에서는 Run 단위 중복 제거를 수행한다. **멀티 워커 환경에서는 Redis 분산 Seen Set 필수.**

## 배경

크롤 1회(Run) 동안 이미 수집한 공지의 `external_id`를 기억해 중복 수집·Upsert를 막아야 한다. 단일 프로세스에서는 `_BoundedSeenSet`으로 메모리 상한을 유지한다. **멀티 워커**에서는 워커 간 동일 URL 중복 크롤을 막기 위해 **Redis SET** 기반 분산 Seen Set을 사용한다.

## 결정

- **단일 워커/Redis 미설정:** `_BoundedSeenSet(max=CRAWL_SEEN_MAX_SIZE)`. 최대 10,000개 `external_id`만 유지. O(1) add/contains. Evict: FIFO.
- **멀티 워커·Redis 설정 시(필수):** `_RedisSeenSet(run_id, redis_url, ttl)`. 키 `dicee:crawl_seen:{run_id}`, TTL 1시간. Redis SET으로 SADD/SISMEMBER. `crawl_college_sync(..., run_id=run_id)` 호출 시 사용.
- **`redis_crawl_seen_required=True`:** Redis Seen 연결 실패 시 즉시 run 실패(no silent fallback). 인메모리 fallback 없음. 멀티 워커 운영 시 True 권장.
- **트레이드오프:** Bounded는 10,000건 초과 시 evict로 재수집 가능. Redis 분산은 Run 단위로 워커 간 공유되어 중복 크롤·IP 밴·트래픽 낭비를 방지한다.

## 참고

- [app/services/crawl_service.py](../../app/services/crawl_service.py): `_BoundedSeenSet`, `_RedisSeenSet`, `crawl_college_sync(..., run_id=...)`, `run_crawl_job_sync`에서 `run_id` 전달.
