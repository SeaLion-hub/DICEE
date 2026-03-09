# 크롤러 이식 검증 체크리스트 (함수형)

새 크롤러 추가·이식 후 **기존 크롤러(yonsei_ai, yonsei_business 등)와 동일한 방식**인지 확인할 때 사용한다.

---

## 최근 점검 결과 (빌드 후 점검)

| 항목 | 결과 |
|------|------|
| **pytest** (test_crawler_discovery + test_crawler_exception_policy + test_tasks_and_config) | 35 passed |
| **validate_crawler_contract()** | 통과 (모든 모듈 get_links/scrape_detail callable 존재) |
| **등록 크롤러 수** | 16 (ai, business, chemistry, dongari, dormitory, engineering, glc, igee, international, library, main, medicine, physics, science, startup, underwood) |

- 2025-03-09: SeaLion-hub/crawler 기준 미등록 9개(chemistry, dongari, dormitory, igee, international, library, physics, startup, main) 이식 완료.

## 1. 모듈 구조 (기존과 동일해야 함)

| 항목 | 기존 패턴 (참조: yonsei_ai, yonsei_business) | 검증 |
|------|-----------------------------------------------|------|
| 스펙 상수 | `CRAWLER_SPEC = CrawlerModuleSpec(college_code=..., display_name=..., list_url=..., get_links="함수명", scrape_detail="함수명")` | |
| 목록 함수 | `def get_<site>_links(list_url: str) -> list[LinkItem]` (이름은 스펙의 `get_links`와 일치) | |
| 상세 함수 | `def scrape_<site>_detail(url: str) -> ScrapeResult` (이름은 스펙의 `scrape_detail`와 일치) | |

- `college_code`: 영문, 소문자, 중복 불가. 시드/트리거에서 `external_id`로 사용.
- `list_url`: 유효한 절대 URL (scheme + netloc 필수). Discovery 시 검증됨.

## 2. HTTP 호출 (기존과 동일해야 함)

| 항목 | 기존 패턴 | 검증 |
|------|-----------|------|
| 목록 페이지 | `fetch_html(list_url, timeout=10[, encoding=...])` 사용 | |
| 상세 페이지 | `fetch_html_detail_cached(url, timeout=10[, encoding=...])` 사용 | |
| 금지 | `requests.get`·`requests.Session` 직접 사용 금지 | |
| 타임아웃 | 모든 fetch에 **timeout 명시** (기본 10초) | |

- 인코딩이 cp949인 사이트만 `encoding="cp949"` 추가 (예: yonsei_business).

## 3. 반환 형식 (파이프라인 계약)

| 함수 | 반환 타입 | 필수 필드 | 선택 필드 |
|------|------------|-----------|-----------|
| get_*_links | `list[LinkItem]` | `url: str` | `no: str`, `title_hint: str` |
| scrape_*_detail | `ScrapeResult` | title, date_str, html_content, images, attachments | - |

- **LinkItem**: `{"url": full_url}` 필수. `no`/`title_hint`는 파이프라인에서 external_id·제목 보조용.
- **ScrapeResult**: `ScrapeResult(title, date_str, html_content, images, attachments)`  
  - `images`: `[{"type": "url"|"base64", "data": url_or_bytes, "name": str}]`  
  - `attachments`: `list[str]` (파일명).

## 4. 예외 처리 (기존과 동일해야 함)

| 상황 | 기존 패턴 | 검증 |
|------|-----------|------|
| fetch 실패 | `HtmlTooLargeError` / `RequestException` catch 후 **re-raise** | |
| 파싱 예외 | `logger.exception(...)` 후 **raise** (빈 리스트/기본값으로 삼키지 않음) | |
| 정상 빈 목록 | 에러가 아닌 경우에만 `return []` | |

- error-handling.md: 크롤러는 실패 시 **예외 전파(raise)**. 에러를 조용히 넘기지 않음.

## 5. Discovery 검증 (빌드 후 필수)

- `app.core.crawler_config._discover_crawler_specs()`가 새 모듈을 자동 수집.
- 조건: `CRAWLER_SPEC` 존재, `list_url` 유효, `get_links`/`scrape_detail` 이름에 해당하는 **callable**이 모듈에 존재.
- 실행: `pytest tests/test_crawler_discovery.py tests/test_crawler_exception_policy.py -v`  
  및 `pytest tests/test_tasks_and_config.py -v` (config에서 크롤러 로딩 검증).

## 6. 참조 구현

- **함수형 (현재 연세 크롤러 대부분)**: [app/services/crawlers/yonsei_ai.py](../app/services/crawlers/yonsei_ai.py), [yonsei_business.py](../app/services/crawlers/yonsei_business.py)
- **클래스형 (BaseCrawler)**: [docs/crawlers/BASE_CRAWLER_TEMPLATE.md](BASE_CRAWLER_TEMPLATE.md)

이식 시 SeaLion 등 외부 모듈은 **함수형**으로 맞추고, 목록/상세 URL·파싱 로직만 참조와 동일하게 유지하며, fetch는 반드시 `fetch_html`/`fetch_html_detail_cached`로 통일한다.
