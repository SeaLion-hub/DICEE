# 배포 가이드 (Railway + Vercel)

## 개요

- 백엔드(API, Worker): **Railway**
- 데이터 저장소: **PostgreSQL + Redis**
- 프론트엔드(6단계 이후): **Vercel**
- 기본 원칙:
  - API 프로세스는 마이그레이션을 실행하지 않는다.
  - 마이그레이션은 Release 단계 또는 별도 migrate 잡에서 1회 실행한다.
  - `APP_ENTRY`를 명시해 프로세스 역할을 강제한다(`api`, `celery`, `migrate`).

**브랜치 보호·SCA·Sentry·로그 전환 체크리스트:** [RUNBOOK_DEPLOY.md](RUNBOOK_DEPLOY.md)

---

## PostgreSQL / pgvector

공지 시맨틱 검색(`notices.embedding`, HNSW)은 **pgvector 확장**이 필요합니다.

- **로컬·CI:** Docker 이미지 `pgvector/pgvector:pg15` 사용 ([`compose.yml`](../compose.yml)의 `db` 서비스, GitHub Actions `services.postgres`와 동일).
- **Railway:** 사용 중인 **PostgreSQL 플랜/템플릿이 `CREATE EXTENSION vector`를 허용하는지** 대시보드·문서로 확인하세요. 확장을 켤 수 없는 템플릿이면 pgvector 지원 인스턴스로 교체하거나, 확장 설치가 가능한 관리형 Postgres로 옮겨야 합니다.
- **마이그레이션:** Alembic `012_notice_embedding`이 `CREATE EXTENSION IF NOT EXISTS vector` 및 `embedding vector(768)` 컬럼·HNSW 인덱스를 적용합니다. 인덱스 생성은 `SET LOCAL statement_timeout = 0`으로 긴 작업을 허용합니다. **대용량 `notices` 테이블**이면 유지보수 창에서 실행하는 것을 권장합니다.
- **실행 주체:** API 프로세스는 마이그레이션을 돌리지 않습니다. Railway **Release Command** `alembic upgrade head` 또는 Compose의 **`migrate` 서비스**만 마이그레이션을 실행합니다 ([Quick Start](#quick-start-5분) 원칙과 동일).

### Alembic 이중 base·빈 DB

히스토리상 **루트 리비전이 두 개**입니다(`001`, `v7_001`). 머지(`007_merge_heads`) 이전까지는 서로 다른 줄기이며, Alembic은 head까지 올리기 위해 **양쪽 조상을 모두 적용**합니다. 적용 순서상 v7 초기 스키마가 먼저 깔린 뒤 레거시 `001`…`006`이 실행될 수 있어, 레거시 쪽은 **`app/legacy_alembic_guard`**로 “이미 v7(colleges.id가 UUID)이면 no-op” 처리합니다. 그래도 `alembic_version`만 어긋난 DB는 기존처럼 `stamp`·수동 정렬이 필요할 수 있습니다.

- **로컬 검증:** 저장소 루트에서 `DATABASE_URL`·`APP_ENTRY=migrate` 설정 후  
  `scripts/check_migrations.ps1`(Windows) 또는 `scripts/check_migrations.sh`(Unix) — `alembic upgrade head` + `alembic check`.
- **적용 순서 확인:** `python scripts/dump_alembic_upgrade_order.py`
- **CI:** `upgrade head` 직후 `alembic check`가 실행됩니다.

**다운그레이드 한계(문서):** `007_merge_heads`의 `downgrade`는 no-op; UUID PK 전환 리비전(`002_notice_uuid`, `004_colleges_users_to_uuid`)은 `NotImplementedError`; `012_notice_embedding` 다운그레이드는 `vector` 확장을 제거하지 않을 수 있습니다. 프로덕션 롤백은 별도 runbook으로 계획합니다.

---

## Quick Start (5분)

1. Railway에서 **New Project → Deploy from GitHub repo**로 서비스 생성
2. Railway에서 **PostgreSQL**, **Redis** 추가
3. API 서비스 Variables 설정
   - `APP_ENTRY=api`
   - `DATABASE_URL=${{Postgres.DATABASE_URL}}` (반드시 private URL)
4. Deploy 설정
   - Start Command: `APP_ENTRY=api uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Release Command: `alembic upgrade head`
5. Networking에서 도메인 생성 후 `GET /health` 200 확인

---

## 핵심 환경 변수

### 공통 필수

| 변수 | 설명 | 예시 |
|------|------|------|
| `APP_ENTRY` | 프로세스 역할 강제 | `api` / `celery` / `migrate` |
| `DATABASE_URL` | PostgreSQL 연결 URL (private 권장) | `${{Postgres.DATABASE_URL}}` |
| `REDIS_URL` | Redis 연결 URL | `${{Redis.REDIS_URL}}` |
| `ALLOWED_ORIGINS` | CORS 허용 도메인 | `https://app.example.com` |

### Auth/보안

| 변수 | 설명 |
|------|------|
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google OAuth |
| `JWT_SECRET` | HS256 사용 시 서명 키 |
| `JWT_PRIVATE_KEY_PEM`, `JWT_PUBLIC_KEY_PEM` | RS256 사용 시 키 |
| `USER_ID_HMAC_KEY` | production에서 필수 |
| `REDIS_BLOCKLIST_FAIL_CLOSED` | production API는 `true` 권장 |
| `TRUSTED_PROXY_IPS` | 신뢰할 프록시 IP 지정 |

### 로깅/관측

| 변수 | 설명 | 권장값 |
|------|------|--------|
| `LOG_FORMAT` | structlog 출력 형식 (`pretty` or `json`) | 기본 `pretty` |

#### `LOG_FORMAT` 안전 전환 절차

1. **staging**에서 `LOG_FORMAT=json` 적용
2. 30~60분 트래픽으로 아래 확인
   - `event_code`, `request_id`, `college_code`, `phase` 필드 파싱/집계 가능
   - 예외 로그 파서 오류 없음
   - 로그 볼륨 급증 없음
3. 문제 없으면 **prod**에 `LOG_FORMAT=json` 적용
4. 문제 발생 시 즉시 `LOG_FORMAT=pretty`로 롤백

---

## 헬스 체크 정책

| 엔드포인트 | 용도 | 기준 |
|------------|------|------|
| `/health` | 기본 생존 확인 | 200 + `{"status":"ok"}` |
| `/live` | liveness | 200 + `{"status":"ok"}` |
| `/ready` | readiness (의존성 확인) | DB/Redis 상태 반영 |

권장:
- 외부 모니터링/업타임 체크는 `/health`
- 트래픽 라우팅(gate)은 `/ready`

---

## Railway 배포

### 1) API 서비스

- Builder: Nixpacks
- Start Command:

```bash
APP_ENTRY=api uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

- Release Command:

```bash
alembic upgrade head
```

중요:
- API Start Command에 `alembic`을 넣지 않는다.
- 릴리즈 단계에서만 마이그레이션 수행.

### 2) Worker 서비스 (Celery)

- Worker는 API와 별도 서비스로 분리
- Start Command (Linux):

```bash
celery -A app.core.celery_app:app worker -l info -O fair -Q critical,crawl,ai --concurrency=1
```

- Windows 로컬 디버그 시:

```bash
celery -A app.core.celery_app:app worker -l info -O fair -Q critical,crawl,ai --pool=solo
```

- **임베딩 백필:** `app.services.tasks.backfill_notice_embedding_task` — `ai` 큐, `GEMINI_API_KEY` 또는 `gemini_api_key` 설정 필요. `backfill_notice_embedding_task.delay("<notice_uuid>")`로 호출. 공지 **제목**만 `text-embedding-004`로 임베딩하며, `embedding`이 이미 있으면 스킵(멱등).

### 3) Cron 트리거

- 권장 방식: Railway Cron 또는 외부 Cron이 `POST /internal/trigger-crawl` 호출
- 필수: `CRAWL_TRIGGER_SECRET` 설정
- 호출 시 헤더:
  - `X-Crawl-Trigger-Secret: <secret>` 또는
  - `Authorization: Bearer <secret>`

---

## Vercel 배포 (6단계 이후)

- `frontend/` 생성 이후 Vercel 프로젝트 연결
- 필수 환경 변수:
  - `NEXT_PUBLIC_API_URL=https://<railway-domain>`
- CORS/Origin은 백엔드 `ALLOWED_ORIGINS`와 정확히 맞춘다.

---

## 운영 체크리스트 (Go-Live)

- [ ] `ENVIRONMENT=production`
- [ ] `APP_ENTRY` 역할별로 서비스 분리(api/celery)
- [ ] `DATABASE_URL` private 주소 사용
- [ ] `USER_ID_HMAC_KEY` 설정
- [ ] `REDIS_BLOCKLIST_FAIL_CLOSED=true` (API)
- [ ] `/health`, `/ready` 정상
- [ ] Release 단계 `alembic upgrade head` 성공 로그 확인
- [ ] `LOG_FORMAT` 전환 시 staging 검증 완료

---

## 트러블슈팅

### 1) `password authentication failed for user "postgres"`

- `DATABASE_URL` 계정/비밀번호 불일치 가능성
- Railway Postgres의 **Variables 또는 Connect에서 제공한 값** 재확인
- `DATABASE_PUBLIC_URL`을 내부 서비스 통신에 사용하지 않았는지 확인

### 2) `connection timeout expired` (Alembic/DB 연결)

- DB 부팅 직후 일시적 타임아웃 가능
- Release 재시도 또는 연결 재시도 관련 설정 검토
- `DATABASE_URL` host/port/protocol 오타 점검

### 3) `Multiple head revisions are present` (Alembic)

- 머지 리비전 누락 가능성
- `alembic/versions` 내 merge head 존재 여부 확인
- CI에서 single-head 검사 통과 여부 확인

### 4) `/internal/trigger-crawl`이 503 반환

- Redis 잠금/멱등성 fail-closed 정책에 의해 차단될 수 있음
- `REDIS_URL`, `REDIS_TRIGGER_IDEMPOTENCY_REQUIRED`, `REDIS_TRIGGER_LOCK_REQUIRED` 점검

### 5) `Can't locate revision identified by '011'` (Alembic)

- DB의 `alembic_version`과 배포된 마이그레이션 세트가 어긋난 경우(011이 코드에 없거나 DB만 앞서간 경우 등).
- **확인:** 현재 브랜치·이미지에 011 리비전 파일이 포함되는지 확인한다.
- DB만 011을 가리키고 코드가 뒤처진 경우에는 운영 절차에 따라 `alembic downgrade` 등으로 맞추거나, 스테이징에서 재현 후 DBA/런북에 따른다.

### 6) `relation "colleges" already exists` (DuplicateTable, upgrade → 001)

- 이미 스키마가 있는 DB에 `alembic_version` 없이 또는 잘못된 베이스에서 `001`이 다시 적용되려 할 때 발생할 수 있다.
- **개발/스테이징 복구(요약):** Railway Postgres `DATABASE_URL`로 접속 가능한지 확인한 뒤, 같은 DB에 `APP_ENTRY=api`로 붙여 `alembic stamp 007_merge_heads`(또는 `alembic stamp head`)로 버전만 맞춘 다음 Redeploy한다. **주의:** 프로덕션 DB에는 반드시 백업·런북에 따른다.

---

## 고급 운영 팁

- DB 커넥션은 API/Worker 합산으로 예산 관리
- 배포 스파이크를 고려해 여유 용량 확보
- Redis 장애 시 fail-open/fail-closed 정책을 엔드포인트별로 구분
- Worker 큐(`critical,crawl,ai`)와 동시성은 점진적으로 튜닝

---

## 2026-02-27 Additions

### New environment variables

- `JWT_SIGNING_MODE` (`auto|hs256|rs256`, default `auto`)
  - `auto`일 때 HS·RS 설정이 모두 있으면 RS를 우선 사용한다.
- `CONTENT_SPOOL_ALLOW_EPHEMERAL` (default `false`)
  - production에서 `CONTENT_UPLOAD_FAILURE_POLICY=fail`이고 `CONTENT_SPOOL_BACKEND=local`이면, 명시적으로 `true`가 아니면 부팅이 실패한다.
- `CONTENT_SPOOL_S3_PREFIX` (default `content-spool`)
  - S3 스풀 객체 prefix.

### Internal API fail-closed update

- `/internal/trigger-crawl`, `/internal/crawl-stats`는 client IP 해석 불가 시 `503` 반환
- `"unknown"` fallback 식별자 경로 제거

### Spool backend update

- `CONTENT_SPOOL_BACKEND=s3`는 drain 경로에서 지원한다.
- local·S3 스풀 엔트리가 동일한 retry·error·dead-letter 메타데이터 스키마를 쓴다.
