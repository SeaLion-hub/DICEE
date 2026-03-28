# DICEE 문서

## 문서 진입점

아래 순서로 읽으면 전략 → 실행 → 주의 → 결정 → 배포 → 게이트 → 기록까지 한 번에 잡을 수 있다.

1. **[ROADMAP](ROADMAP.md)** — 전략·마일스톤·기술 기둥·성공 지표
2. **[ROADMAP_PHASES](ROADMAP_PHASES.md)** — 단계별 할 일·확정 사항·예상 문제·추가 검토
3. **[CAUTIONS](CAUTIONS.md)** — 코딩 전·중 체크리스트
4. **[decisions/](decisions/)** — ADR (아키텍처 결정 기록). 예: [database-spec](decisions/database-spec.md)
5. **[DEPLOYMENT](DEPLOYMENT.md)** — Railway·Vercel·환경변수·빌드
6. **[RELEASE_GATE](RELEASE_GATE.md)** — 머지/배포 전 P0·P1·Go/No-Go
7. **[WORK_LOG](WORK_LOG.md)** — 실제 수정 기록

---

## 폴더별 역할


| 폴더/파일                                        | 역할                                                                                                                    |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| **루트 (Core)**                                | ROADMAP, ROADMAP_PHASES, CAUTIONS, DEPLOYMENT, RELEASE_GATE, WORK_LOG — 항상 docs/ 직하에 유지.                              |
| **[reports/](reports/)**                     | 시점성·기준선 리포트. 벤치마크 인사이트, 품질/타입 기준선 등. 브라우저용 정적 HTML(예: [online_viewer_net.htm](reports/online_viewer_net.htm))도 여기 둔다. |
| **[reports/baselines/](reports/baselines/)** | 품질·mypy·auth 등 기준선 스냅샷. CI/회귀 비교용.                                                                                    |
| **[reports/archive/](reports/archive/)**     | 과거 참고용 문서 (예: 계획 평가 보강). 현재 할 일은 ROADMAP_PHASES·WORK_LOG 참고.                                                          |
| **[logs/](logs/)**                           | (예비) 월별·주제별 로그 분리 시 사용. 현재 WORK_LOG는 단일 파일.                                                                           |
| **[decisions/](decisions/)**                 | ADR. 데이터베이스 명세, 인증, 크롤, Redis 등 설계 결정.                                                                                |
| **[rules/](rules/)**                         | 코딩·에러 핸들링 등 매뉴얼. .cursor/rules에서 참조.                                                                                  |
| **[runbooks/](runbooks/)**                   | 장애·복구 절차(API 에러 버짓, 크롤 재시도·DLQ, Redis, 롤백 등).                                                                         |


---

## 기준선·리포트 위치 (이동 안내)

- **QUALITY_BASELINE**, **MYPY_BASELINE_BY_MODULE**, **auth_baseline_20260301**, **baseline_grep_count** → [reports/baselines/](reports/baselines/)
- **online_viewer_net.htm** (공지 분류 체계 리포트 뷰어) → [reports/online_viewer_net.htm](reports/online_viewer_net.htm)
- **BENCHMARK_INSIGHTS** → [reports/](reports/)
- **PLAN_REMEDIATION_68** → [reports/archive/](reports/archive/)

