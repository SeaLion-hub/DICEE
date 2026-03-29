# 크롤러 공통 유틸 (함수형 계약 유지)

## 맥락

- 런타임은 `CRAWLER_SPEC` + 모듈 함수가 단일 진실원천이다.
- `BaseCrawler`는 스캐폴드·문서용이며 프로덕션 yonsei 모듈은 상속하지 않는다.
- 링크 메타는 파이프라인 계약 `crawl_contracts.LinkItem`에 맞춘다 (`title_hint` 선택).

## 결정

1. **날짜:** `normalize_notice_date` / `normalize_notice_date_split_tokens`(의과·AI 등 토큰 분리)를 `notice_dates.py`에 둔다.
2. **링크 URL dedupe:** `dedupe_link_dicts_by_url`로 O(n²) `not any` 패턴을 제거한다.
3. **이미지:** KBoard·NXB 계열에서 재사용 가능한 `extract_images_from_container`를 둔다.
4. **예외:** 상세 HTML이 과대할 때 조용한 빈 `ScrapeResult` 대신 `docs/rules/error-handling.md`에 맞춰 예외를 전파한다 (GLC 동기 상세는 `RequestException` 체인).
5. **fetch 옵션:** 사이트별 `encoding`/timeout은 `fetch_config.CrawlerFetchConfig` 인스턴스로 선언한다 (경영: `BUSINESS_SITE_FETCH`).
6. **BoardView 제목:** `cms_board_view.board_view_title_from_soup`로 ID `BoardViewTitle` + h2/h3 폴백을 공유한다.

## 품질 게이트

- `pytest` 전체 통과 (크롤·exception policy·신규 유틸 테스트 포함).
- **2026-03-29:** `pytest -q` → 448 passed, 4 skipped (약 30s).

## 대안으로 버린 것

- 모든 크롤러를 `BaseCrawler`로 일괄 이전 (런타임 계약과 불일치, 범위 과다).
- 공대·경영대 단일 DOM 추상화 (사이트별 특수성 비용 대비 이득 낮음).
