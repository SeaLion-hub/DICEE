# 배포·품질 게이트 런북

CI, GitHub, Railway, Sentry를 한 흐름으로 맞출 때 사용한다. 상세 변수는 [DEPLOYMENT.md](DEPLOYMENT.md)를 본다.

SLO·큐·DLQ 기준 롤백 트리거는 [runbooks/release-rollback.md](runbooks/release-rollback.md)를 본다.

## 1. GitHub: `main` 브랜치 보호 (필수)

저장소 **Settings → Branches → Branch protection rule** (`main`):

1. **Require a pull request before merging** 켜기.
2. **Require status checks to pass before merging** 켜기.
3. Required checks에 다음을 추가한다 (이름은 Actions 탭의 job 이름과 일치해야 한다).
   - `lint-test` (`.github/workflows/ci.yml`의 메인 job; 동일 job 안에 Ruff·Mypy·pytest·**`pip-audit (SCA)`**까지 포함되며, 마지막 단계 실패 시 머지 불가)
   - (권장) `compose-smoke` — Docker 스모크까지 머지 조건에 넣을지 팀에서 결정.

직접 `main` 푸시는 막는다. 긴급 패치도 PR을 통해 CI green 후 머지한다.

## 2. 릴리스 체크리스트 (Railway)

배포 전에 다음을 확인한다.

- [ ] API: `APP_ENTRY=api`, Worker: `APP_ENTRY=celery` (또는 문서된 worker 진입).
- [ ] **Release Command**: `alembic upgrade head` (API Start Command에 넣지 않음).
- [ ] Release 로그에서 마이그레이션 성공 확인.
- [ ] 배포 후 `GET /health` 200, 필요 시 `GET /ready`로 DB·Redis 확인.
- [ ] GitHub **Actions**에서 해당 커밋의 `lint-test` (및 compose-smoke) 성공 확인.

## 3. 롤백

- **애플리케이션**: Railway에서 **이전 성공 배포로 되돌리기**(Rollback / Redeploy 이전 이미지).
- **데이터베이스**: `downgrade` 자동 롤백은 운영에서 쓰지 않는 것을 원칙으로 한다. 스키마 변경은 아래 expand/contract로 계획한다.

## 4. DB 마이그레이션: expand / contract

앱 롤백만으로 서비스를 복구하려면, 마이그레이션은 가능한 한 **호환** 순서를 지킨다.

1. **Expand**: 새 컬럼·테이블·인덱스 추가(기본값 허용). 구버전 앱도 읽기/쓰기 가능하게 유지.
2. **배포**: 새 앱 버전 배포.
3. **Contract**: 더 이상 구버전이 없다고 확정된 뒤, 사용 중지 컬럼 제거·제약 변경 등 파괴적 변경을 별도 마이그레이션으로 수행.

한 번에 “컬럼 삭제 + 코드에서만 참조”처럼 하면 롤백 시 앱과 DB가 어긋난다.

## 5. Sentry·릴리즈 상관

- **Railway Variables** (API·Worker 모두 동일 권장):
  - `SENTRY_DSN` — 프로젝트 DSN.
  - `SENTRY_RELEASE` — Git SHA 또는 버전 문자열 (예: `git rev-parse --short HEAD`를 빌드/배포 시 주입).
- Sentry 프로젝트에서 **environment**를 staging / production 등으로 구분한다.
- **알람(최소)**:
  - 새 이슈(First seen) 또는 에러 급증 알림 1개 이상 설정.
  - 샘플링·`before_send` 스크러빙은 코드 [`app/core/sentry_config.py`](../app/core/sentry_config.py) 정책을 따른다.

## 6. 로그: `LOG_FORMAT=json` 검증 후 프로덕션

[DEPLOYMENT.md](DEPLOYMENT.md)의 “`LOG_FORMAT` 안전 전환 절차”를 따른다.

**스테이징 검증 체크리스트 (예시)**

- [ ] 로그 한 줄이 JSON으로 파싱되는가.
- [ ] `request_id`(또는 동일 의미의 trace)로 요청 단위 검색이 되는가.
- [ ] `event_code`, `college_code`, `phase` 등 운영 필드가 필요 시 남는가.
- [ ] 예외 로그에 파서 오류·이중 이스케이프가 없는가.
- [ ] 로그 볼륨이 비정상 급증하지 않는가.

문제 없으면 프로덕션에 `LOG_FORMAT=json` 적용. 이슈 시 즉시 `pretty`로 되돌린다.

## 7. 메트릭·가용성

- Prometheus 형식: `GET /internal/metrics` ([`app/api/internal.py`](../app/api/internal.py)). `METRICS_ALLOWED_IPS` 미설정 시 차단(fail-closed) — [DEPLOYMENT.md](DEPLOYMENT.md) 참고.
- Railway만으로 스크레이프가 어렵다면 외부 업타임/합성 체크로 `/health` 또는 `/ready`를 주기 호출한다.

## 8. SCA: `pip-audit`

- PR CI에서 `requirements.txt` + `requirements-dev.txt`를 대상으로 `pip-audit`를 실행한다 (Ubuntu, `PYTHONIOENCODING=utf-8`).
- 실패 시 의존성 업그레이드 또는 [`.github/pip-audit-allowlist.txt`](../.github/pip-audit-allowlist.txt)에 CVE ID를 한 줄 하나씩 적고, 사유를 PR 본문에 남긴다.

## 9. 주간 SCA (선택)

`.github/workflows/sca-weekly.yml`이 주기적으로 동일 감사를 실행한다. PR을 막지 않고 추세를 본다.

## 10. 버그픽스 회귀 규칙

깨진 동작을 고친 PR에는 **같은 PR**에 그 경로를 막는 테스트를 최소 1개 둔다. 크리티컬 경로 목록은 [`tests/CRITICAL_PATHS.md`](../tests/CRITICAL_PATHS.md)를 본다.
