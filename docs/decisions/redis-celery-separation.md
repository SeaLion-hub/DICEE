# ADR: Redis Celery 전용 URL 분리

## 상태

수락 (2025-02)

## 배경

앱은 Blocklist·Trigger lock용 Redis 풀을 이미 분리해 두었으나, Celery broker/result_backend는 `REDIS_URL`과 동일한 인스턴스를 사용했다. Celery 부하(큐·결과 백엔드)가 인증/락용 Redis에 영향을 주지 않도록 URL 수준 분리를 지원한다.

## 결정

- `REDIS_CELERY_URL`(설정: `redis_celery_url`)을 추가한다. 비어 있으면 기존처럼 `REDIS_URL` 사용.
- Celery 앱은 broker/result_backend에 `redis_celery_url or redis_url`을 사용한다.
- 라우팅 도입 시 태스크는 명명 큐(critical, crawl, ai)로만 전달되므로, **워커는 소비할 큐를 반드시 명시**해야 한다. 단일 워커: `-Q critical,crawl,ai`.

## 결과

- Celery만 별도 Redis 인스턴스 또는 DB 번호를 쓸 수 있음.
- 배포 문서(DEPLOYMENT.md) 및 .env.example에 REDIS_CELERY_URL·워커 -Q 옵션 안내 추가.

---

## 운영·장애 시 동작 (보강)

- **Broker/Result backend**: `REDIS_CELERY_URL`(또는 `REDIS_URL`)과 동일한 Redis를 쓰는 경우, 해당 Redis 장애 시 워커는 자동 재연결을 시도하며, 결과 조회(`task.get()` 등)는 실패할 수 있다. 클라이언트는 503 또는 타임아웃 후 재시도로 처리하는 것을 권장한다.
- **broker_transport_options / result_backend visibility**: 기본값은 설정 `celery_broker_visibility_timeout_seconds`(env `CELERY_BROKER_VISIBILITY_TIMEOUT_SECONDS`, 기본 3600초)와 동일. 워커가 메시지 처리 중 죽으면 이 시간이 지난 뒤 다른 워커가 같은 메시지를 다시 가져갈 수 있다. 장시간 크롤은 [CAUTIONS.md](../CAUTIONS.md)의 visibility·중복 소비 문구를 따른다.
- **task_acks_late=True**, **task_reject_on_worker_lost=True**: 메시지 유실을 줄이기 위해, 태스크 완료 후 ack하고 워커 손실 시 메시지를 다시 큐에 넣는다.

### crawl_college_task 실행 클레임 (Redis)

- **목적**: 동일 Celery 메시지가 동시에 두 워커에서 실행되는 것을 줄이기 위해 `app/core/redis.py`의 `claim_crawl_task_execution`(SET NX)을 사용한다.
- **TTL·재전달**: 고정 장기 TTL만 쓰면 워커 비정상 종료 후 키가 남아 **정상 재전달**을 `duplicate_delivery`로 오인할 수 있다. 그래서 클레임 TTL은 `crawl_task_execution_claim_ttl_seconds`(env `CRAWL_TASK_EXECUTION_CLAIM_TTL_SECONDS`, 기본 120초)로 짧게 두고, 워커 생존 중에는 트리거 락 하트비트 주기와 같이 `renew_crawl_task_execution_claim`(EXPIRE)으로 연장한다. 프로세스가 죽으면 갱신이 멈춰 키가 만료되고, 브로커 재전달 시 다시 SET NX가 성공할 수 있다.
- **DB 멱등**: 동일 `task_id`에 대한 `crawl_run_tasks` / `crawl_runs` 갱신은 저장소 계층에서 이미 재시도 친화적으로 설계되어 있다.

---

## Redis 클라이언트 용도 정책

- **API 프로세스**: Blocklist용·Trigger lock용 비동기 Redis 클라이언트는 lifespan에서 각각 별도 풀으로 생성되어 `AppState`에 보관된다. read_cache(`app/core/read_cache.py`)는 `/internal/crawl-stats` 등에서 **trigger_lock용 Redis 클라이언트**를 사용한다. 향후 Soft TTL 캐시(`get_cache_with_soft_ttl`/`set_cache_with_soft_ttl`)를 도입할 때도 동일한 trigger_lock 클라이언트 또는 전용 캐시 클라이언트를 사용할 수 있다.
- **Celery 워커**: heartbeat·락 해제는 `app/core/redis.py`의 **동기 Redis 싱글톤**(`_get_sync_redis_client`) 하나를 재사용한다. 연결 churn을 막기 위해 호출마다 from_url/close를 하지 않는다.
