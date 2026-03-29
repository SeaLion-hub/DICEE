# 공개·매칭 공지 목록 페이지네이션

## 결정

- 목록 정렬은 `published_at DESC NULLS LAST`, `created_at DESC`, `id DESC`로 고정된다.
- **키셋 커서**(`next_cursor` → 다음 요청의 `cursor`)가 다음 페이지의 권장 방식이다. 정렬과 일치한다.
- **offset**은 `cursor`가 없을 때만 사용한다. 저장소는 offset 윈도우에서 `limit+1`로 조회해, 더 있으면 `next_cursor`를 채운다.
- 매칭 피드(`GET /v1/notices/matched`)는 내부적으로 동일 저장소를 여러 번 호출할 수 있다. 저장소가 첫 호출부터 `next_cursor`를 줄 수 있어야 저밀도 매칭 시 추가 배치가 가능하다.

## API

- `GET /v1/notices`: `NoticeListResponse.items`, `next_cursor`, `limit`.
- `GET /v1/notices/matched`: `MatchedNoticeListResponse` + `requires_profile`.

## 품질 게이트

- `tests/test_notice_repository_pagination.py`, 공지·매칭 API 관련 테스트로 회귀 방지.

**Quality Gates:** `pytest` 전체 통과(구현 시점).
