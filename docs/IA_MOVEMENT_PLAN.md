# 문서 IA 이동 계획표 (유지/이동/아카이브)

| 구분 | 파일 | 비고 |
|------|------|------|
| **유지 (루트 Core)** | ROADMAP.md | 전략·마일스톤 |
| **유지** | ROADMAP_PHASES.md | 단계별 할 일·확정 사항 |
| **유지** | CAUTIONS.md | 코딩 시 주의 |
| **유지** | DEPLOYMENT.md | 배포·환경변수 |
| **유지** | RELEASE_GATE.md | P0/P1·Go/No-Go |
| **유지** | WORK_LOG.md | 작업 기록 |
| **이동 → reports/** | BENCHMARK_INSIGHTS.md | 시점성 리포트 |
| **이동 → reports/baselines/** | QUALITY_BASELINE.md | 품질 기준선 |
| **이동 → reports/baselines/** | MYPY_BASELINE_BY_MODULE.md | mypy 기준선 |
| **이동 → reports/baselines/** | auth_baseline_20260301.md | Auth 기준선 |
| **이동 → reports/baselines/** | baseline_grep_count.txt | grep 기준 |
| **이동 → reports/archive/** | PLAN_REMEDIATION_68.md | 과거 참고용 |
| **유지** | decisions/*.md | ADR (경로 변경 없음) |
| **유지** | rules/*.md | 매뉴얼 (경로 변경 없음) |

---

## 검증 (이동 후)

- **깨진 마크다운 링크**: `](QUALITY_BASELINE|MYPY_BASELINE|auth_baseline|BENCHMARK_INSIGHTS|PLAN_REMEDIATION)` 패턴으로 docs/ 검색 → **0건**. 이동한 파일을 가리키는 마크다운 링크 없음.
- **WORK_LOG 내 "docs/ROADMAP", "docs/DEPLOYMENT" 등**: 과거 작업 **기록 문구**(어떤 파일을 수정했는지)이지 링크가 아님. 수정 불필요.
- **이동된 파일 내 상대경로**: `reports/BENCHMARK_INSIGHTS.md` → `../ROADMAP_PHASES.md`; `reports/archive/PLAN_REMEDIATION_68.md` → `../../ROADMAP_PHASES.md`, `../../WORK_LOG.md`, `../../DEPLOYMENT.md`. 모두 수정 완료.
- **.gitignore**: `docs/BENCHMARK_INSIGHTS.md` → `docs/reports/BENCHMARK_INSIGHTS.md` 로 경로 갱신 완료.

---

## 변경 파일 목록 및 요약

| 구분 | 경로 | 요약 |
|------|------|------|
| **신규** | docs/README.md | 문서 진입점·폴더별 역할·기준선 이동 안내 |
| **신규** | docs/IA_MOVEMENT_PLAN.md | 이동 계획표·검증 결과·변경 요약 |
| **신규** | docs/reports/.gitkeep, docs/reports/baselines/.gitkeep, docs/reports/archive/.gitkeep, docs/logs/.gitkeep | 디렉터리 유지용 |
| **이동** | docs/reports/BENCHMARK_INSIGHTS.md | docs/ → reports/, 링크 ../ROADMAP_PHASES.md 로 수정 |
| **이동** | docs/reports/baselines/QUALITY_BASELINE.md | docs/ → reports/baselines/ |
| **이동** | docs/reports/baselines/MYPY_BASELINE_BY_MODULE.md | docs/ → reports/baselines/ |
| **이동** | docs/reports/baselines/auth_baseline_20260301.md | docs/ → reports/baselines/ |
| **이동** | docs/reports/baselines/baseline_grep_count.txt | docs/ → reports/baselines/ |
| **이동** | docs/reports/archive/PLAN_REMEDIATION_68.md | docs/ → reports/archive/, 링크 ../../ 로 수정 |
| **삭제** | docs/BENCHMARK_INSIGHTS.md, docs/QUALITY_BASELINE.md, docs/MYPY_BASELINE_BY_MODULE.md, docs/auth_baseline_20260301.md, docs/baseline_grep_count.txt, docs/PLAN_REMEDIATION_68.md | 이동 후 제거 |
| **수정** | docs/WORK_LOG.md | 월별 분리 원칙·문서 이동 안내 섹션 추가 |
| **수정** | docs/ROADMAP.md | 관련 문서 표에 README 링크 추가 |
| **수정** | .gitignore | BENCHMARK_INSIGHTS 경로를 docs/reports/ 로 갱신 |
