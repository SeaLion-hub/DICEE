# Crawlee 패턴 차용, 프레임워크 비도입

**Status:** APPROVED (문서)  
**Date:** 2026-03-29

## Context

Apify Crawlee는 요청 큐, 스토리지 분리, 세션·프록시, 훅, 지연 커밋, 관측 등 검증된 패턴을 제공한다. DICEE는 이미 FastAPI, Celery, Redis, PostgreSQL, 동기 DB 워커로 유사 축을 갖추고 있다.

## Decision

- **crawlee-python / Node Crawlee를 코어에 통합하지 않는다.** 빅뱅 이전 비용·운영 복잡도가 이익을 압도한다.
- **패턴만 이식한다:** 청크 커밋·`expunge_all`, 트리거 락·멱등, 디스패치 메모리 백프레셔, 레지스트리 SSOT, 선택적 프록시 URL 주입, 트리거/크롤 메트릭, 문서화된 용량 표.

## Consequences

- 긍정: 기존 CI·아키텍처 규칙(AsyncSession vs Celery 동기 DB)을 깨지 않는다.
- 부정: Crawlee 생태계 툴링(예: 일부 스토리지 어댑터)을 그대로 쓰지 못한다. 필요 시 개별 라이브러리만 검토한다.

## References

- [docs/CRAWL_WORKER_CAPACITY.md](../CRAWL_WORKER_CAPACITY.md)
- [docs/crawler-registry.md](../crawler-registry.md)
- [docs/crawler-http-proxy.md](../crawler-http-proxy.md)

**Quality gates:** `pytest` 통과·관련 회귀 테스트 유지 후 merge.
