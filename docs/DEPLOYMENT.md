# 배포 환경 (Railway · Vercel)

## 목차

- [요약](#요약)
- [진입점(고정)](#진입점고정)
- [비용·리소스](#비용리소스)
- [운영 DB 백업](#운영-db-백업)
- [로컬 개발 참고](#로컬-개발-참고)
- [OAuth 핸드쉐이크 (2단계 확정)](#oauth-핸드쉐이크-2단계-확정)
- [Railway (백엔드)](#railway-백엔드)
  - [프로젝트 생성·연동](#1-프로젝트-생성연동)
  - [서비스 추가 (단계별)](#2-서비스-추가-단계별)
  - [환경 변수 (Variables)](#3-환경-변수-variables)
  - [빌드·실행 설정](#4-빌드실행-설정)
  - [도메인](#5-도메인)
  - [Cron(스케줄 실행, 3단계 이후)](#6-cron스케줄-실행-3단계-이후)
- [Vercel (프론트엔드, 6단계)](#vercel-프론트엔드-6단계)

---

## 요약

| 구분 | 플랫폼 | 비고 |
|------|--------|------|
| 백엔드 API | **Railway** | PostgreSQL, Redis 추가. 웹은 Nixpacks, Playwright 워커는 Dockerfile. |
| 프론트엔드 | **Vercel** | 6단계에서 Next.js 생성·배포. `frontend/` 등 폴더는 **6단계 전까지 없음**. |

---

## 진입점(고정)

- **백엔드 앱 진입점**: `app.main:app`
- **Start Command(웹 서비스)**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **원칙**: 루트에 `app/` 패키지(폴더) 유지. `Start Command`/진입점은 문서와 코드가 항상 일치해야 함.

## 비용·리소스

- Railway 플랜별 제한(서비스 수, 메모리, 실행 시간)을 대시보드에서 확인.
- 웹 + DB + Redis + 워커 동시 운영 시 월 예상 비용 상한을 단계별로 체크.
- 초과 시 알림 또는 스케일 다운 정책을 두면 변동에 대비하기 좋음.

## 운영 DB 백업

- **Railway 사용 시**: Railway 대시보드에서 PostgreSQL 서비스 선택 → **Backups** 탭에서 자동 백업 활성화(플랜별 제공). 스냅샷 주기·보관 일수를 확인해 두고, 장애 시 **Restore**로 복구 가능.
- **복구 시나리오**: 백업에서 복원한 뒤 `DATABASE_URL`이 새 인스턴스를 가리키면 앱이 자동으로 새 DB에 연결. 필요 시 `alembic upgrade head`로 스키마 일치 확인.
- **자체 호스팅 시**: `pg_dump` 스케줄(Cron)·저장소(S3 등)와 복구 절차를 별도 문서에 정리.

---

## 로컬 개발 참고

- **Windows + Celery**: 기본 prefork 풀은 Windows에서 동작하지 않음. 워커 실행 시 **`--pool=solo`** 필수. 예: `celery -A app.worker worker -l info --pool=solo`. (README 로컬 실행 참고.)
- PostgreSQL 포트가 5432가 아니면 URL에 `:5433` 등 명시.
- **데이터베이스 생성** 후 마이그레이션:
  - `createdb -U postgres -p 5433 dicee`
  - 또는 `psql -U postgres -p 5433 -c "CREATE DATABASE dicee;"`
- `alembic upgrade head` 실행 전에 `dicee` DB가 존재해야 함.
- **Celery 워커를 로컬(PC)에서 돌릴 때**:
  - `REDIS_URL`에 **Railway 내부 URL**(`redis.railway.internal`)을 넣으면 로컬에서는 DNS 조회 실패(`getaddrinfo failed`). 로컬 Redis를 띄우고 `REDIS_URL=redis://localhost:6379/0` 사용하거나, `.env`에서 `REDIS_URL`을 비우면 기본값 `redis://localhost:6379/0` 사용.
  - **Windows**에서는 기본 prefork 풀에서 billiard 세마포어 오류가 날 수 있음. `celery -A app.worker worker -l info --pool=solo` 로 실행.

---

## OAuth 핸드쉐이크 (2단계 확정)

프론트(Vercel)와 백엔드(Railway)가 다른 도메인. 토큰 전달 방식:

1. 프론트에서 구글 OAuth → **Authorization Code** 획득
2. 프론트가 백엔드 `POST /v1/auth/google`에 **code** 전달
3. 백엔드가 구글에 code 검증 → **Access JWT + Refresh JWT** 발급
4. **응답 body JSON**으로 토큰 반환: `{ "access_token": "...", "refresh_token": "...", "token_type": "bearer", "expires_in": 600 }` (expires_in은 JWT_ACCESS_EXPIRE_SECONDS 설정값.)
5. 프론트는 access_token을 저장(메모리/로컬스토리지 등) 후 API 호출 시 `Authorization: Bearer <token>` 헤더에 포함

CORS: `ALLOWED_ORIGINS`에 프론트 도메인 등록. credentials: 프론트가 쿠키를 보내지 않으면 `credentials: "omit"` 또는 omit.

---

## Railway (백엔드)

### 1. 프로젝트 생성·연동

1. [Railway](https://railway.app) 로그인 후 **New Project**.
2. **Deploy from GitHub repo** 선택 후 이 저장소 연결.
3. 브랜치 선택(예: `main`). 푸시 시 자동 빌드·배포.

### 2. 서비스 추가 (단계별)

**웹 서버 (1단계~)**

- GitHub 연동으로 생성된 **Service** 하나가 FastAPI 앱용.
- **Settings → General**: Root Directory는 비워 두거나 백엔드 루트로 설정.

**PostgreSQL (2단계)**

- **+ New** → **Database** → **PostgreSQL** 선택.
- DB 서비스 **Variables** 탭에서 연결 정보 확인.
- **웹 서비스** Variables에 `DATABASE_URL` 추가.  
  URL 스킴만 `postgresql+asyncpg://` 로 바꿔서 넣기.

**Redis (3단계)**

- **+ New** → **Database** → **Redis** 선택.
- Redis의 `REDIS_URL` 등을 **웹 서비스·Celery 워커 서비스** Variables에 각각 추가.
- **Railway Redis는 TLS 사용 시 `rediss://`** URL을 제공할 수 있음. Celery broker_url 설정 시 **redis://·rediss://** 모두 대응하고, TLS(`rediss://`)일 때는 **ssl_cert_reqs=None** 등 옵션 적용해 연결 실패 방지. (로컬은 보통 `redis://`.)
- **영속성(AOF/RDB)·Railway Redis 플랜 확인**: Redis는 Celery **broker·알림 큐**로 사용되므로 재시작/장애 시 큐 유실을 막기 위해 **AOF(Append Only File)** 또는 **RDB** 백업이 켜져 있는지 확인. **Railway 무료/저가형 플랜**은 재시작 시 데이터가 날아가는 경우가 있으므로, 배포 전 **AOF 설정이 가능한 플랜인지** 반드시 확인. (ROADMAP "진행 시 예상 문제·대비" Redis 영속성 참고.)
- **visibility_timeout**: 크롤 태스크는 수 분~수십 분 걸릴 수 있음. `app/worker.py`에서 **broker_transport_options = {"visibility_timeout": 3600}**(1시간) 설정. 다중 워커 시 타임아웃보다 오래 걸리면 같은 메시지가 재전달될 수 있으므로 확인.

### 3. 환경 변수 (Variables)

웹 서비스(및 워커 서비스) **Variables** 탭에서 추가. 새 변수 추가 시 `.env.example`도 함께 갱신.

| 변수 | 설명 | 적용 시점 |
|------|------|-----------|
| `SENTRY_DSN` | Sentry 에러 모니터링 DSN | 1단계~ |
| `DATABASE_URL` | `postgresql+asyncpg://...` | 2단계~. **비밀번호는 영문·숫자만** 사용. **시스템 환경변수가 .env보다 우선** → Windows에서 `echo $env:DATABASE_URL`로 확인 후, 프로젝트용이 아니면 제거. |
| `DB_CONNECT_RETRIES` | 연결 실패 시 재시도 횟수. 기본 5. | 2단계 (선택, Railway 권장) |
| `DB_CONNECT_RETRY_INTERVAL_SEC` | 재시도 간격(초). 기본 2. | 2단계 (선택) |
| `REDIS_URL` | Redis 연결 URL. Railway는 **rediss://**(TLS) 제공 가능. Celery broker가 rediss 시 SSL 옵션 적용. | 3단계~ |
| `CRAWL_TRIGGER_SECRET` | Cron이 POST /internal/trigger-crawl 호출 시 검증용 시크릿 (헤더 또는 쿼리로 전달) | 3단계 Cron 연동 시 |
| `POLITE_DELAY_SECONDS` | 요청/페이지 간 최소 딜레이(초). 대상 서버 부하·IP 차단 완화. 기본 1. | 3단계 (선택) |
| `JWT_SECRET` | JWT 서명용 비밀키 (강한 랜덤 문자열) | 2단계 Auth 후 |
| `JWT_ACCESS_EXPIRE_SECONDS` | Access 토큰 만료(초). 기본 600(10분). 탈퇴/탈취 시 노출 시간 최소화. | 2단계 (선택) |
| `REDIS_BLOCKLIST_FAIL_CLOSED` | Redis 장애 시 True=인증 거부(Fail-Closed), False=서명만 검증 후 통과(Fail-Open). 기본 True. | 2단계 Auth (Blocklist 사용 시) |
| `REDIS_BLOCKLIST_MAX_CONNECTIONS` | Blocklist용 Redis 비동기 풀 크기. Uvicorn 동시 처리량에 맞게. 기본 20. | 2단계 Auth (Blocklist 사용 시) |
| `JWT_REFRESH_EXPIRE_DAYS` | Refresh 토큰 만료(일). 기본 7. | 2단계 (선택) |
| `GOOGLE_CLIENT_ID` | 구글 OAuth 2.0 클라이언트 ID | 2단계 Auth (구글 먼저) |
| `GOOGLE_CLIENT_SECRET` | 구글 OAuth 2.0 클라이언트 시크릿 | 2단계 Auth |
| `ALLOWED_ORIGINS` | 프론트 도메인, 쉼표 구분 (예: `https://xxx.vercel.app`) | 6단계 연동 시 |
| 기타 | Gemini API 키 등 | 해당 기능 단계 |

(나중에 카카오 등 추가 시 `KAKAO_CLIENT_ID` 등 동일 방식으로 Variables + `.env.example`에 추가.)

**크롤 운영 정책:** FastAPI 내 크롤 트리거(POST /internal/trigger-crawl 또는 동기 호출)는 **개발·소량 테스트용**이다. **프로덕션 정기 크롤은 Celery 워커만 사용**한다. Cron이 6시간마다 trigger-crawl을 호출하면 Celery 태스크가 enqueue되고 워커가 실행한다.

**첨부파일 저장 원칙:** 첨부파일은 **원격 URL(또는 파일명) 리스트만** DB(Notice.attachments JSONB)에 보관한다. **로컬 파일시스템에 다운로드·저장하지 않는다.** (Railway 등 컨테이너는 휘발성 파일시스템이므로 재시작 시 파일이 사라진다.) 클라이언트가 직접 원본 URL로 다운로드하거나, 백엔드를 거칠 경우 **S3 등 외부 오브젝트 스토리지**로 업로드하는 파이프라인만 사용한다.

### 4. 빌드·실행 설정

**웹 서버 (1~2단계, Nixpacks)**

- **Settings → Build**: Builder **Nixpacks** 유지.
- **Settings → Deploy** → **Start Command**:
  - `nixpacks.toml`에 마이그레이션 자동 실행 + 앱 시작 포함. Start Command를 **비워 두면** 이 설정 사용.
  - 커스텀 Start Command 사용 시: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`

**Playwright Celery 워커 (3단계~, Dockerfile 필수)**

- **새 서비스** 추가. 같은 repo 사용, **Dockerfile**로 빌드.
- **Settings → Build**: Builder **Dockerfile** 선택. 경로 예: `./Dockerfile.worker` 또는 `./Dockerfile`.
- **Settings → Deploy** → **Start Command**: `celery -A app.worker worker -l info --concurrency=1` (OOM 방지: 동시 브라우저 개수 제한.)
- Dockerfile에 **반드시** 포함: `RUN playwright install --with-deps chromium`. Playwright 실행 시 `--no-sandbox`, `--disable-dev-shm-usage` 옵션 사용(ROADMAP 3단계 참고).

### 5. 도메인

- **Settings → Networking** → **Generate Domain** → `xxx.up.railway.app` 부여.
- 이 URL로 `GET /health` 등 확인.

### 6. Cron(스케줄 실행, 3단계 이후)

- **추천: Railway Cron(또는 외부 Cron) + 내부 API 호출.** Celery Beat는 서비스 추가 비용이 들므로 사용하지 않음.
- **구현**: FastAPI에 **POST /internal/trigger-crawl** 엔드포인트 추가. 요청 시 **보안 키**(헤더 예: `X-Crawl-Trigger-Secret` 또는 `Authorization: Bearer <secret>`, 쿼리 `?secret=...`) 검증. 검증 통과 시 Celery 크롤 태스크 enqueue. Cron이 **6시간마다**(ROADMAP 확정. IP 차단 리스크 완화) 위 URL을 호출.
- **환경 변수**: `CRAWL_TRIGGER_SECRET`(또는 동일 용도 키 이름)을 Railway Variables에 등록. 엔드포인트에서 이 값과 비교.
- Railway에 Cron Job이 없으면 **외부 Cron 서비스**(cron-job.org 등)에서 웹 서버 URL `POST https://xxx.up.railway.app/internal/trigger-crawl` 호출 + 보안 키 전달.
- **재수집·복구**: 특정 단과대만 삭제 후 다시 수집할 때 — 로컬 또는 서버에서 `python scripts/delete_notices_for_rerun.py --college=<code>` (옵션 `--before`/`--after` YYYY-MM-DD). 이후 `POST <BACKEND_URL>/internal/trigger-crawl?college_code=<code>` 호출(헤더 `X-Crawl-Trigger-Secret` 또는 `Authorization: Bearer <CRAWL_TRIGGER_SECRET>`).

---

## Vercel (프론트엔드, 6단계)

- **프론트 폴더**는 6단계에서 Next.js 프로젝트 생성 시 만듦(예: `frontend/` 또는 루트를 Next로).
- Vercel에서 **Import Git Repository** 후 해당 폴더를 **Root Directory**로 지정.
- 환경 변수: `NEXT_PUBLIC_API_URL`(백엔드 Railway URL), 구글 로그인용 클라이언트 ID 등.
- 상세는 6단계 진행 시 ROADMAP·이 문서에 추가.
