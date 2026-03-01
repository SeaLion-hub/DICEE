# crawl_runs 옵션 B — 스키마 정합화 이슈 (별도 이슈)

**현재 정책**: crawl_runs는 **복합 PK (id, started_at)** 유지 ([crawl-runs-composite-pk-contract](crawl-runs-composite-pk-contract.md)). 옵션 B(id 단독 PK 전환) 검토 시에만 이 템플릿을 사용한다.

옵션 B를 진행할 때 **별도 이슈**로 관리하며, 이슈 본문에 아래를 **반드시 명시**한다.

## 명시할 항목

### 1. 데이터 이관 검증

- 이전 후 **row 수** 검증: 기존 `crawl_runs` 총 행 수 vs `crawl_runs_new` 총 행 수.
- **id 유일성** 검증: `SELECT id, count(*) FROM crawl_runs_new GROUP BY id HAVING count(*) > 1;` → 0행 여부.
- 검증 실패 시 롤백 절차로 전환.

### 2. 롤백

- 실패 시 **기존 테이블/파티션 복구** 절차.
- `crawl_runs_new` drop, 기존 `crawl_runs` 유지. 앱은 기존 스키마(id + started_at) 계약 유지.

### 3. 락/다운타임

- 마이그레이션 중 **테이블 락** 유무·예상 구간.
- **예상 다운타임** 또는 **온라인 전환 전략**(예: 트리거/이중 쓰기로 무중단 전환) 명시.

## 마이그레이션 개요 (참고)

- `crawl_runs_new` 생성: PK `(id)`, `started_at` 등 기존 컬럼 유지.
- 기존 `crawl_runs`에서 id당 1행만 이전: `DISTINCT ON (id) ... ORDER BY id, started_at DESC`.
- 기존 테이블/파티션 drop, `crawl_runs_new` → `crawl_runs` rename.
- 모델·리포지토리에서 `started_at` PK 제거, id 단독 조회로 정리.

이 문서는 이슈 템플릿으로 사용하고, 실제 작업 시 "데이터 이관 검증/롤백/락 시간"을 이슈 본문에 채워 넣는다.
