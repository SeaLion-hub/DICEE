# ADR: 크롤 링크 수 상한 (OOM 선제 대응)

**상태**: 채택  
**배경**: 대규모 링크 유입 시 `remaining`, `retry_queue`, `links` 전체가 메모리에 상주해 단일 노드 OOM 위험이 있음. 스트리밍/Redis 큐는 추후 확장으로 두고, 당장 Run당 링크 수 상한으로 선제 대응한다.

---

## 결정

- **상한**: `MAX_LINKS_PER_RUN = 50_000`. `links`를 이 길이로 자른 뒤 `_collect_payloads_sync`/`_collect_payloads_async`에 전달. 초과 시 로그 경고.
- **동기·비동기 공통**: `crawl_college_sync`, `crawl_college` 모두 적용.
- **Phase 2 (추후)**: 링크를 제너레이터/스트리밍으로 받거나 Redis 큐로 나누어 워커가 청크만 소비하는 방식은 별도 ADR·구현으로 진행. 당분간은 상한·cap으로 OOM 경로만 제거.

---

## 참고

- [app/services/crawl_service.py](../../app/services/crawl_service.py): `MAX_LINKS_PER_RUN`, `links_raw[:MAX_LINKS_PER_RUN]`.
