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
