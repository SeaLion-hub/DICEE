# 크롤 워커 용량·백프레셔 (Railway / Celery)

Crawlee의 `AutoscaledPool`(CPU·메모리 피드백)에 해당하는 개념을 **DICEE 스택**에서 어떻게 다루는지 한곳에 고정한다.  
상세 배포는 [DEPLOYMENT.md](DEPLOYMENT.md), 단계별 정책은 [ROADMAP_PHASES.md](ROADMAP_PHASES.md)를 본다.

## 프로세스·큐

| 구성 요소 | 권장·기본값 | 비고 |
|-----------|-------------|------|
| Celery worker CLI | `-Q critical,crawl,ai` | [Dockerfile.worker](../Dockerfile.worker) |
| Worker concurrency | `--concurrency=1` | Playwright·대용량 HTML 시 OOM 완화. 동시에 여러 Chromium 금지(프로젝트 규칙). |
| `celery_worker_prefetch_multiplier` | `1` ([app/core/config/base.py](../app/core/config/base.py)) | prefetch=1은 공정성(`-O fair`)과 맞물려 큐 백로그가 쌓이면 자연스러운 백프레셔. |
| DB 워커 동시성 가정 | `db_celery_concurrency` | [app/core/database.py](../app/core/database.py) 풀 크기 계산에 사용. |

## 메모리·디스패치 백프레셔

API 프로세스에서 `CeleryCrawlDispatcher`가 `apply_async` 직전에 RSS를 측정한다([app/adapters/celery_crawl_dispatcher.py](../app/adapters/celery_crawl_dispatcher.py)).

| 설정 | 기본 | 의미 |
|------|------|------|
| `celery_dispatch_memory_soft_limit_mb` | 1024 | 초과 시 추가 `countdown`(백프레셔) |
| `celery_dispatch_backpressure_step_seconds` | 30 | 메모리 초과 단계당 추가 지연 |
| `celery_dispatch_backpressure_max_seconds` | 300 | 추가 지연 상한 |

Railway 플랜 RAM이 더 작으면 `soft_limit`을 **할당 메모리의 70~80%** 근처로 낮춘다. `psutil` 미설치 환경에서는 스냅샷이 비어 백프레셔가 0일 수 있다.

## 크롤 런타임·청크 (OOM·지연 커밋)

| 설정 | 기본 | 역할 |
|------|------|------|
| `crawl_upsert_chunk_size` | 50 | NoticeDraft 버퍼가 이 크기에 도달하면 upsert·(옵션) chunk 커밋·`expunge_all` ([app/services/crawl/pipeline_sync.py](../app/services/crawl/pipeline_sync.py)). |
| `crawl_collect_in_flight_limit` | 500 | 수집 동시성 상한. |
| `crawl_max_links_per_run` | 50000 | 한 런당 링크 캡. |
| 본문 HTML 상한 | 10MiB (`MAX_HTML_BYTES`) | [app/services/crawl_payload.py](../app/services/crawl_payload.py) |

**배치 커밋 경계:** `on_chunk_processed`가 있으면 chunk마다 `session.commit()` 후 `session.expunge_all()`을 호출한 뒤 AI 큐 적재 콜백을 실행한다. Crawlee의 handler 결과 지연 플러시와 같은 **“청크 단위 일관성”** 패턴이다.

## 선택적 아웃바운드 프록시

워커가 외부 HTTP를 나갈 때만 사용. 설정·환경 변수는 [docs/crawler-http-proxy.md](crawler-http-proxy.md) 참고.

## 외부 크롤러 레포

사이트별 스크래퍼는 [SeaLion-hub/crawler](https://github.com/SeaLion-hub/crawler)와 병행할 수 있다. 레지스트리 SSOT는 [docs/crawler-registry.md](crawler-registry.md).

## LLM 브라우저 PoC (선택)

범위·격리·비용 상한은 [docs/crawl-llm-browser-poc.md](crawl-llm-browser-poc.md).
