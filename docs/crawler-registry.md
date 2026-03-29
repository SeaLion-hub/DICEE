# 크롤러 레지스트리 SSOT (DICEE 앱 내)

Crawlee의 **라우터·핸들러 레지스트리**와 같이, 단과대 코드 → 실행 모듈 매핑은 **한 메커니즘**만 쓴다.

## 코드 SSOT

| 항목 | 위치 | 설명 |
|------|------|------|
| 자동 수집·검증 | [app/core/crawler_config.py](../app/core/crawler_config.py) | `pkgutil`로 `app.services.crawlers.*` 스캔, `CrawlerModuleSpec` 필수. |
| 공개 맵 | `COLLEGE_CODE_TO_MODULE`, `CRAWLER_CONFIG` | `_ensure_registry()` 지연 초기화(첫 접근 시 discovery). |
| 런타임 해석 | [app/services/crawl/runtime.py](../app/services/crawl/runtime.py) | `_resolve_module_and_list_url` 등. |
| 트리거 대상 목록 | [app/services/internal_crawl_service.py](../app/services/internal_crawl_service.py) | `college_code` 생략 시 `COLLEGE_CODE_TO_MODULE` 키 전체 순회. |

## 신규 단과대 체크리스트

1. `app/services/crawlers/<모듈>.py`에 `CRAWLER_SPEC: CrawlerModuleSpec` 정의.
2. `get_notice_links` / `scrape_detail`(또는 스펙에 명시한 이름) 구현.
3. `pytest` 및 크롤 계약 테스트 통과.
4. (선택) 외부 레포 [SeaLion-hub/crawler](https://github.com/SeaLion-hub/crawler)와 동기화 시 README·모듈명 정합.

## 공통 HTTP 래퍼 (외부 레포 이슈 템플릿)

SeaLion-hub/crawler 쪽에서 아래를 한 이슈로 묶는 것을 권장한다.

- **타임아웃·재시도:** `tenacity` 또는 공유 정책과 `Retry-After` ([runtime.py](../app/services/crawl/runtime.py) 참고).
- **User-Agent:** `CRAWLER_HEADERS` ([crawler_config.py](../app/core/crawler_config.py))와 정합.
- **프록시:** DICEE 설정 `crawler_http_proxy_url` 또는 `CRAWLER_HTTP_PROXY` — [crawler-http-proxy.md](crawler-http-proxy.md).

DICEE 앱 내 크롤러 모듈은 동일 헬퍼를 쓰도록 점진 이관하면 된다.
