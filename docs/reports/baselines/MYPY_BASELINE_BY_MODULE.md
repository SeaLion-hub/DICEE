# Mypy `app` 기준선

## 현재 (2026-03-23)

- **명령**: `python -m mypy app`
- **결과**: **Success: no issues found** (118 source files)
- **선행 작업**: BeautifulSoup `Tag` 좁히기·`ensure_str_attr`/`class_list_from_tag`·`collect_sync` seen 클로저·`InstructorRetryException` 폴백 이름 분리·`streaming` `Any` 클라이언트·`types-psutil` dev 의존성. 사전 스냅샷: [MYPY_APP_ERRORS_PRE_REMEDIATION_2026-03-23.md](MYPY_APP_ERRORS_PRE_REMEDIATION_2026-03-23.md)

---

## 과거 스냅샷 (Phase 2 전, 2026-02-25)

`pyproject.toml`의 app 관련 mypy overrides를 **일시 제거**한 뒤 `mypy app` 실행하여 모듈별 에러 개수를 집계한 기준선.

- **총 에러 수**: 68 (17개 파일)

### 모듈별 에러 개수 (당시)

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

### 재현 방법 (과거 비교용)

1. `pyproject.toml`에서 app 관련 `[[tool.mypy.overrides]]` 블록을 주석 처리 또는 제거.
2. `mypy app` 실행.
3. 출력에서 `: error:` 라인만 모듈별로 집계.
