# Mypy `app` 오류 사전 스냅샷 (정리 작업 전)

- **촬영 시점**: 2026-03-23
- **명령**: `python -m mypy app`
- **요약**: 약 **134 errors / 14 files** (117 modules checked)
- **목표**: 본 정리 후 `mypy app` 0 errors 및 [MYPY_BASELINE_BY_MODULE.md](MYPY_BASELINE_BY_MODULE.md) 갱신

## 파일별 오류 건수 (prefix 집계)

| 건수 | 경로 prefix |
|------|----------------|
| 24 | `app/services/ai_pipeline.py` |
| 19 | `app/services/crawlers/yonsei_dongari.py` |
| 13 | `app/services/crawlers/yonsei_physics.py` |
| 12 | `app/services/crawlers/yonsei_chemistry.py` |
| 12 | `app/services/crawlers/yonsei_library.py` |
| 12 | `app/services/crawlers/yonsei_startup.py` |
| 11 | `app/services/crawlers/yonsei_igee.py` |
| 10 | `app/services/crawlers/yonsei_dormitory.py` |
| 8 | `app/services/crawlers/yonsei_international.py` |
| 5 | `app/services/ai/streaming.py` |
| 5 | `app/services/crawlers/yonsei_main.py` |
| 1 | `app/adapters/celery_crawl_dispatcher.py` |
| 1 | `app/services/crawl/collect_sync.py` |
| 1 | `app/services/crawl/downloader_middleware.py` |

## 주요 원인 유형

- BeautifulSoup `PageElement` vs `Tag` 미좁힘 (`union-attr`, `attr-defined`)
- `InstructorRetryException` ImportError 폴백 시 동일 이름 재할당 (`misc`)
- 스트리밍 Instructor API vs `InstructorExtractionClient` Protocol 불일치
- `psutil` 미스텁 (`import-untyped`)
- `seen` 클로저에서 `Optional` 미좁힘 (`operator`)
