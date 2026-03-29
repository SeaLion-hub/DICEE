# 시맨틱 공지 검색 API 계약

## 결정

- `POST /v1/notices/search/semantic`은 **커서·오프셋 페이지네이션을 제공하지 않는다**.
- 응답은 `NoticeSemanticSearchResponse`: `items`, `limit`만 포함한다. 클라이언트는 `limit`(1–100)으로 한 번에 받을 최대 건수를 제한한다.
- 목록 공지 API(`GET /v1/notices`)와 달리 정렬 기준이 벡터 거리이므로, 안정적 keyset 페이징을 넣으려면 별도 설계가 필요하다. **현재 구현 범위에서는 시맨틱 커서 페이징을 넣지 않는다.**

## 오류

- 기간 역전: 요청 검증 422.
- 공백만 있는 `query`: 서비스에서 400(빈 쿼리).
- 미등록 `college_external_id`: 404.

**Quality Gates:** `pytest` 전체 통과(구현 시점).
