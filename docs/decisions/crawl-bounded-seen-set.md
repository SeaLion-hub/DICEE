# ADR: 크롤 중복 제거용 Bounded Seen Set

## 상태

**적용 완료.** 동기 크롤(`crawl_college_sync`)에서는 `_BoundedSeenSet(max=CRAWL_SEEN_MAX_SIZE)`를 사용하여 Run 단위 중복 제거를 수행하며, 메모리 상한을 유지한다.

## 배경

크롤 1회(Run) 동안 이미 수집한 공지의 `external_id`를 기억해 중복 수집·Upsert를 막아야 한다. 무제한 `set`을 쓰면 Run당 공지 수가 매우 많을 때 메모리가 커질 수 있다.

## 결정

- **구조:** `app.services.crawl_service._BoundedSeenSet`. 최대 **10,000개**(`CRAWL_SEEN_MAX_SIZE`) `external_id`만 유지. O(1) add/contains.
- **Evict 정책:** 크기가 `max_size`를 초과하면 **가장 오래 추가된 항목(FIFO)**부터 제거한 뒤 새 항목을 추가한다. 청크마다 `clear()`를 호출하지 않으며, Run 전체 동안 한 번만 생성·유지된다.
- **트레이드오프:** 한 Run에서 10,000건을 초과하는 공지를 수집할 경우, evict된 오래된 ID가 페이지네이션·중복 응답 등으로 다시 등장하면 재수집·재 Upsert될 수 있다. 현재 규모와 단과대별 공지량을 고려해 10,000으로 두며, 필요 시 상수만 조정한다.

## 참고

- [app/services/crawl_service.py](../../app/services/crawl_service.py): `_BoundedSeenSet` 클래스(88~108라인), `crawl_college_sync`에서 `seen = _BoundedSeenSet(CRAWL_SEEN_MAX_SIZE)` 사용(455라인).
