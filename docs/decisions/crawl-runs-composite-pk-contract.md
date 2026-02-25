# crawl_runs 복합 PK와 앱 계약

**관련**: [crawl-runs-monitoring.md](crawl-runs-monitoring.md), [app/models/crawl_run.py](../../app/models/crawl_run.py), [app/repositories/crawl_run_repository.py](../../app/repositories/crawl_run_repository.py)

---

## 1. 스키마와 앱 계약

- **스키마**: `crawl_runs`는 복합 PK `(id, started_at)`을 가진다. RANGE(started_at) 파티셔닝 호환을 위해 유지한다.
- **앱 계약**: 애플리케이션은 **run_id(id)당 1행만** 생성·조회한다. 동일 `id`로 복수 행을 넣지 않으며, 조회 시에도 `id` 단독 + `order_by(started_at.desc()).limit(1)`로 결정적 1행을 가정한다.
- **리포지토리**: `create_or_update_crawl_run_sync`, `update_crawl_run_sync` 등은 모두 `id == run_id` 조건과 `order_by(started_at.desc()).limit(1)`로 "1행"을 전제로 동작한다.

## 2. 구조적 부채

- DB는 동일 `id`에 여러 행을 허용하는 스키마이지만, 앱은 1행만 다룬다. 따라서 **데이터 모델과 앱 계약이 문서/코드로만 맞춰져 있고**, 스키마로는 강제되지 않는다.
- 동일 `id` 복수 행이 생기면(버그 또는 수동 데이터) 리포지토리의 `scalar_one_or_none()` 등이 기대와 어긋날 수 있다.

## 3. 운영·개선 방향

- **단기**: 계약을 코드·문서에 명시(모델/리포지토리 docstring, 본 결정 문서). 선택적으로 DB에 `UNIQUE(id)` 제약을 두면 앱 계약이 스키마로 강제된다(파티션 테이블인 경우 제약 위치 확인 필요).
- **감시**: 동일 `id`에 2행 이상 존재하는지 주기적으로 검사하는 쿼리·알림은 [crawl-runs-monitoring.md](crawl-runs-monitoring.md)를 따른다.
- **장기**: 모델 주석대로 **id 단일 PK 마이그레이션**을 검토한다. 파티셔닝 정책과 충돌하지 않는 범위에서 마이그레이션 경로를 정리한다.
