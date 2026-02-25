# Mypy 오류 모듈별 스냅샷 (Phase 2 전)

`pyproject.toml`의 app 관련 mypy overrides를 **일시 제거**한 뒤 `mypy app` 실행하여 모듈별 에러 개수를 집계한 기준선입니다.  
Phase 2 단계별 진행 시 "이전 스냅샷 대비 감소" 여부로 검증합니다.

- **촬영일**: 2025-02-25 (계획 실행 시)
- **총 에러 수**: 68 (17개 파일)

## 모듈별 에러 개수

| 모듈 | 에러 수 |
|------|--------|
| app.core.api_rate_limit | 1 |
| app.core.celery_app | 1 |
| app.core.crawl_rate_limit | 1 |
| app.core.redis | 5 |
| app.core.storage | 5 |
| app.main | 4 |
| app.api.health | 1 |
| app.api.internal | 1 |
| app.services.auth_service | 3 |
| app.services.crawl_service | 7 |
| app.services.crawlers.yonsei_ai | 5 |
| app.services.crawlers.yonsei_business | 7 |
| app.services.crawlers.yonsei_engineering | 8 |
| app.services.crawlers.yonsei_glc | 5 |
| app.services.crawlers.yonsei_medicine | 9 |
| app.services.crawlers.yonsei_science | 1 |
| app.services.crawlers.yonsei_underwood | 6 |

## 재현 방법

1. `pyproject.toml`에서 app 관련 `[[tool.mypy.overrides]]` 3개 블록을 주석 처리 또는 제거.
2. `mypy app` 실행.
3. 출력에서 `: error:` 라인만 모듈별로 집계.
