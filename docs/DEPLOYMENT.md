# 배포 환경 (Railway · Vercel)

## 목차

- [요약](#요약)
- [진입점(고정)](#진입점고정)
- [헬스체크·장애 전파 방지](#헬스체크장애-전파-방지)
- [비용·리소스](#비용리소스)
- [DB 연결 수 및 용량 계획](#db-연결-수-및-용량-계획)
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
- **진입점 환경 변수**: **APP_ENTRY**(또는 **ROLE**) **필수(Fail-fast)**. 웹 서비스는 `APP_ENTRY=api`, Celery 워커는 `APP_ENTRY=celery`. 미설정 시 부팅 실패.
- **Start Command(웹 서비스)**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (workers 미지정 시 **기본 1 프로세스**.)
- **원칙**: 루트에 `app/` 패키지(폴더) 유지. `Start Command`/진입점은 문서와 코드가 항상 일치해야 함.

## 헬스체크·장애 전파 방지

플랫폼(로드밸런서·오토스케일러)이 Redis/DB 장애 시에도 인스턴스를 과도하게 제거하지 않도록, 엔드포인트 역할을 분리한다.

| 엔드포인트 | 용도 | 동작 |
|------------|------|------|
| **/health** | 플랫폼 헬스체크 | 프로세스 기동 여부만 확인. DB/Redis 미체크. 항상 200 `{"status":"ok"}`. |
| **/ready** | 준비 상태·내부 모니터링 | DB 및 Redis(blocklist·trigger_lock) 연결 확인. 실패 시 503. |
| **/live** | Liveness(재시작 유도) | 프로세스 생존만. DB/Redis 미체크. 200 `{"status":"ok"}`. |

**운영 설정**  
- 플랫폼 헬스체크/오토스케일 프로브는 **/health** 사용. Redis 장애 시에도 인스턴스가 비정상 판정되지 않는다.  
- **/ready**는 내부 모니터링·경보 및 배포 롤링 시 "새 인스턴스가 트래픽 받을 준비가 되었는지" 판단용. 의존성 상태를 그대로 노출하므로 blocklist Redis 장애 시에도 503을 반환한다. `redis_blocklist_fail_closed`는 인증 경로(JWT blocklist 체크)에서만 사용한다.
- **롤링 배포**: 동시 교체 인스턴스 수 1개로 제한. 새 인스턴스가 /ready 200을 반환한 뒤에만 다음 인스턴스 교체.  
- 모니터링에 `active_connections / App_budget` 비율 메트릭을 두고, 0.7·0.85 초과 시 경고를 권장한다.

## 비용·리소스

- Railway 플랜별 제한(서비스 수, 메모리, 실행 시간)을 대시보드에서 확인.
- 웹 + DB + Redis + 워커 동시 운영 시 월 예상 비용 상한을 단계별로 체크.
- 초과 시 알림 또는 스케일 다운 정책을 두면 변동에 대비하기 좋음.

## DB 연결 수 및 용량 계획

배포 스케일·롤링 배포 시 DB 연결 수가 예측 가능하도록 풀을 명시하고, **피크 시** 예산을 초과하지 않도록 한다.

### 공식 (프로파일 R 기준 예산 검사)

- **기본**: `Total_pool_conn = API_conn + Worker_conn`
- **피크**: `Peak_pool_conn = Total_pool_conn × Deploy_surge_factor` (기본 2. 롤링/오토스케일 구간에 순간 2배까지 늘 수 있음을 가정.)
- **프로파일 R (권장·예산 검사용)**: `P_async=4`, `O_async=6` → API 프로세스당 10. `P_sync=2`, `O_sync=0` → 워커당 2.  
  **API**: `API_conn = N_api_instances × N_uvicorn_workers × 10`  
  **Worker**: `Worker_conn = N_worker_instances × N_celery_concurrency × 2`
- **Celery 연결 수 (모드별)**  
  - **`--pool=solo`** (Windows·문서 기본): 1 프로세스 1풀.  
    `Worker_conn = N_worker_instances × 1 × 2`  
  - **`--pool=prefork`** (Linux 등): 자식 프로세스마다 풀 1개.  
    `Worker_conn = N_worker_instances × N_celery_concurrency × 2`  
  prefork 사용 시 concurrency 1 증가 = 풀 1개(연결 2) 추가이므로 스케일 전에 용량을 다시 계산할 것.
- **안전 예산**: `App_budget = floor((DB_max_connections - DB_RESERVED) × 0.7)`  
  **DB_RESERVED**: PostgreSQL 등에서 슈퍼유저/관리용 예약 연결 수. 기본 3.
- **통과 조건**: `Peak_pool_conn ≤ App_budget`. 운영상한(85% 안전 마진) 권장: `Peak_pool_conn ≤ 0.85 × App_budget`.

### 문서 기본 배포 예시 (프로파일 R)

| 항목 | 값 |
|------|-----|
| N_api_instances | 1 |
| N_uvicorn_workers | 1 |
| N_worker_instances | 1 |
| N_celery_concurrency | 1 |
| P_async + O_async | 10 (프로파일 R: 4+6) |
| P_sync + O_sync | 2 (프로파일 R: 2+0) |
| Total_pool_conn | 1×1×10 + 1×1×2 = **12** |
| Peak_pool_conn (surge 2) | 24 |

### DB max_connections별 안전 판정 (프로파일 R, Reserved=3)

| DB_max | App_budget | 산술상한 N_api (하드) | 운영상한 N_api (85% 마진) |
|--------|------------|----------------------|---------------------------|
| 50 | 32 | 1 | 1 |
| 100 | 67 | 3 | 2 |
| 150 | 102 | 4 | 4 |
| 200 | 137 | 6 | 5 |

운영상한 계산: `Peak_pool_conn ≤ 0.85 × App_budget`. Replica max는 **DB_API_INSTANCES**와 일치하거나 그 이하로 설정할 것.

스케일 시 **Peak_pool_conn**이 **App_budget**을 넘지 않도록, DB_max 상향 또는 인스턴스/workers/conc 조정이 필요하다. 풀 크기·타임아웃은 환경 변수(`DB_POOL_SIZE_ASYNC`, `DB_POOL_MAX_OVERFLOW_ASYNC`, `DB_POOL_TIMEOUT_ASYNC`, `DB_POOL_SIZE_SYNC` 등)로 조정 가능.

### 과다 설정 방지 (부팅 시 예산 검사)

부팅 시 **프로파일 R** 기준으로 `Peak_pool_conn > App_budget` 여부를 검사한다. **effective_max_connections**는 환경 변수 `DB_MAX_CONNECTIONS`가 있으면 그 값(운영 오버라이드), 없으면 DB에서 조회한 `max_connections`를 사용.

- **기본**: 초과 시 **critical 로그** 및 Sentry(`context=db_capacity`) 후 부팅 계속.
- **`DB_POOL_STRICT_BUDGET=true`**: 초과 시 **부팅 실패**(RuntimeError).  
예산/인스턴스 수는 `DB_API_INSTANCES`, `DB_UVICORN_WORKERS`, `DB_WORKER_INSTANCES`, `DB_CELERY_CONCURRENCY`, `DB_RESERVED`, `DEPLOY_SURGE_FACTOR` 등으로 반영(기본값 1, 1, 1, 1, 3, 2.0).
- **Kubernetes/HPA 사용 시**: `DB_POOL_STRICT_BUDGET=true`는 **권장하지 않음**. 스케일 업 시 신규 파드가 동시에 부팅 검사에 걸려 전부 실패할 수 있음. 용량 계획을 맞춘 뒤 사용하거나, 배포 전 수동 검사·단일 인스턴스용으로만 사용할 것.

### 오토스케일·Replica 정책 (DB 용량별)

Replica max는 **DB_API_INSTANCES**와 일치하거나 그 이하로 설정할 것. 이를 초과하면 커넥션 예산 검증이 무의미해진다.

| DB_max_connections | Replica min | Replica max | DB_API_INSTANCES (권장) |
|--------------------|-------------|-------------|-------------------------|
| 50 | 1 | 1 | 1 |
| 100 | 1 | 2 | 2 (운영상한 기준) |
| 150 | 2 | 4 | 4 |
| 200 | 2 | 5 | 5 |

**스케일 트리거 (인프라/IaC 또는 플랫폼 설정)**  
- **Scale-out**: CPU > 65% 3분 연속, 또는 p95 latency > 400ms 3분 연속. Step: 한 번에 +1 replica. Cooldown: 180초.
- **Scale-in**: CPU < 35% 10분 연속.

모니터링(Grafana 등)에서 동일 기준으로 알림 규칙을 두면 일관된 대응이 가능하다. 커넥션 예산은 **산술상한(hard)** 외에 **운영상한(85% 마진)** 기준을 함께 사용하며, Replica max는 운영상한에 맞추고, 긴급 시에만 일시적으로 hard 상한까지 허용(이 경우 추가 모니터링 필수).

### 앱 내부 타임아웃 정책 (운영 권장)

인프라(게이트웨이/로드밸런서)의 request timeout은 **항상 앱 내부 타임아웃보다 길게** 설정할 것. 그렇지 않으면 앱이 정상 처리 중인데 상위에서 끊어 장애로 오인할 수 있다.

| 구분 | 기본값 | 환경 변수 |
|------|--------|-----------|
| DB 풀 대기 타임아웃(Async) | 5초 | `DB_POOL_TIMEOUT_ASYNC` |
| SQL statement timeout | 30초 | `DB_STATEMENT_TIMEOUT_MS` |
| Redis 연결 타임아웃 | 2초 | `REDIS_SOCKET_CONNECT_TIMEOUT` |
| Redis 소켓 타임아웃 | 5초 | `REDIS_SOCKET_TIMEOUT` |

### Sync 풀 정책 (timeout / recycle)

Celery Sync 풀에는 **대기 시간 상한**(`pool_timeout`)과 **유휴 연결 재활용 주기**(`pool_recycle`)를 두어, 대기 무한·유휴 연결 단절을 방지한다. 환경 변수: `DB_POOL_TIMEOUT_SYNC`(기본 30초), `DB_POOL_RECYCLE_SYNC`(기본 300초, -1이면 미설정).

### 권장 메트릭 (관측성)

풀 포화는 로그만으로는 늦게 잡힌다. 아래 메트릭을 수집·알림에 활용할 것을 권장한다.

| 메트릭 | 설명 |
|--------|------|
| **db_pool_checked_out** (또는 checked_out_count) | 현재 사용 중인 연결 수 |
| **pool_wait_time** | 풀에서 연결을 기다린 시간(초 또는 ms) |
| **timeout_count** | 풀 대기 타임아웃 발생 횟수(증분 또는 누적) |

구현은 SQLAlchemy 이벤트 또는 커스텀 래퍼로 가능. Sentry/메트릭 수집기 연동 시 위 항목으로 풀 포화 알림을 설정하면 좋다.

### 게이트웨이/로드밸런서 타임아웃 (엔드포인트별)

인프라 레벨에서 아래 request timeout을 설정할 것. 앱 내부 타임아웃보다 길어야 한다.

| 경로 | request timeout (권장) |
|------|------------------------|
| `/v1/auth/google` | 12초 |
| `/v1/auth/refresh` | 5초 |
| `/internal/trigger-crawl` | 5초 |
| `/internal/crawl-stats` | 3초 |

---

## Go-Live 검증 (부하 테스트·장애 훈련)

머지/배포 Go/No-Go 판정은 [RELEASE_GATE](RELEASE_GATE.md)(P0·P1 체크·필수 검증 커맨드) 기준으로 수행한다.  
베타 → 프로덕션 전환 전 아래 검증을 수행한다.

### 통과 기준 (공통)

- 오류율 **&lt; 1%**
- Auth 계열 엔드포인트: **p95 &lt; 500ms**
- DB active connection **&lt; App_budget × 0.7**

### 부하 테스트 시나리오 (각 10분)

| 대상 엔드포인트 | 목적 | 관측 메트릭 |
|-----------------|------|-------------|
| `/v1/auth/refresh` | Refresh 토큰 갱신 부하 | 오류율, p95, DB 커넥션 수 |
| `/v1/auth/google` | 구글 로그인·토큰 발급 부하 | 오류율, p95, Google API 지연 |
| `/internal/trigger-crawl` | Cron 트리거 부하 | 오류율, p95, Redis 락·레이트 리밋 |

각 시나리오별 목표 RPS·동시 사용자 수는 환경에 맞게 정한 뒤, 위 통과 기준을 만족하는지 확인한다.

### 장애 훈련 (Chaos Test)

| 시나리오 | 기대 동작 | 관측 메트릭 |
|----------|-----------|-------------|
| **Redis 다운 5분** | Circuit Breaker 열림 → Fail-open. 인증은 서명 검증만으로 통과. Blocklist 미동작 구간 허용. | 인증 성공률, Circuit 상태 전이, 로그/Sentry |
| **DB 지연 2배** | statement_timeout·pool_timeout 동작. 장기 쿼리 차단, 풀 대기 타임아웃 발생 시 적절한 에러 응답. | timeout_count, 5xx 비율, DB active connection |
| **Google API 지연 주입** | `/v1/auth/google` 요청 타임아웃·재시도. 사용자 경험 저하 최소화 또는 명확한 에러 메시지. | p95, 오류율, 클라이언트 타임아웃 |

각 시나리오별로 "기대 동작"과 "실제 관측해야 하는 메트릭"을 실행 전에 정리하고, 실행 후 결과를 기록해 재발 대비한다.

## 운영 DB 백업

- **Railway 사용 시**: Railway 대시보드에서 PostgreSQL 서비스 선택 → **Backups** 탭에서 자동 백업 활성화(플랜별 제공). 스냅샷 주기·보관 일수를 확인해 두고, 장애 시 **Restore**로 복구 가능.
- **복구 시나리오**: 백업에서 복원한 뒤 `DATABASE_URL`이 새 인스턴스를 가리키면 앱이 자동으로 새 DB에 연결. 필요 시 `alembic upgrade head`로 스키마 일치 확인.
- **자체 호스팅 시**: `pg_dump` 스케줄(Cron)·저장소(S3 등)와 복구 절차를 별도 문서에 정리.

---

## 로컬 개발 참고

- **Windows + Celery**: 기본 prefork 풀은 Windows에서 동작하지 않음. 워커 실행 시 **`--pool=solo`** 필수. 예: `celery -A app.core.celery_app:app worker -l info -O fair --pool=solo`. (README 로컬 실행 참고.)
- PostgreSQL 포트가 5432가 아니면 URL에 `:5433` 등 명시.
- **데이터베이스 생성** 후 마이그레이션:
  - `createdb -U postgres -p 5433 dicee`
  - 또는 `psql -U postgres -p 5433 -c "CREATE DATABASE dicee;"`
- `alembic upgrade head` 실행 전에 `dicee` DB가 존재해야 함.
- **Celery 워커를 로컬(PC)에서 돌릴 때**:
  - `REDIS_URL`에 **Railway 내부 URL**(`redis.railway.internal`)을 넣으면 로컬에서는 DNS 조회 실패(`getaddrinfo failed`). 로컬 Redis를 띄우고 `REDIS_URL=redis://localhost:6379/0` 사용하거나, `.env`에서 `REDIS_URL`을 비우면 기본값 `redis://localhost:6379/0` 사용.
  - **라우팅 도입 후** 워커는 `-Q critical,crawl,ai` 필수. **Windows**에서는 `celery -A app.core.celery_app:app worker -l info -O fair -Q critical,crawl,ai --pool=solo` 로 실행.

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
- **웹 서비스** Variables에 **변수 이름** `DATABASE_URL`(고정, 앱이 이 이름만 읽음)으로 다음 중 하나 설정.
  - **권장: 변수 참조**  
    값: `${{Postgres.DATABASE_URL}}` (Postgres 서비스 이름이 다르면 해당 이름으로. 예: `${{PostgreSQL.DATABASE_URL}}`)  
    Railway 최신 Postgres에서는 **Postgres 서비스의 `DATABASE_URL`이 내부(private) URL**이다. **`DATABASE_PUBLIC_URL`을 참조하면 안 됨** — 공개 URL 참조 시 내부에서 인증 실패가 날 수 있음.
  - **직접 입력**  
    DB 서비스 **Variables** 또는 **Connect** 탭에서 **내부 연결 URL**(호스트가 `postgres.railway.internal`인 것) 전체를 복사한 뒤, 스킴만 `postgresql://` → **`postgresql+psycopg://`** 로 바꿔 넣기. (앱에서 `postgres://` 주소를 받으면 **postgresql+psycopg**로 자동 정규화하므로, Railway가 주는 URL을 그대로 넣어도 동작함.) 비밀번호에 특수문자(`@`, `#`, `%`, `:` 등)가 있으면 URL 인코딩(`%40`, `%23`, `%25`, `%3A` 등) 필요.
- **Railway가 부여한 user/비밀번호를 그대로 사용해야 함.** 로컬용 `postgres:postgres` 등을 넣으면 `password authentication failed for user "postgres"` 로 기동 실패.

**Redis (3단계)**

- **+ New** → **Database** → **Redis** 선택.
- Redis의 `REDIS_URL` 등을 **웹 서비스·Celery 워커 서비스** Variables에 각각 추가.
- **Railway Redis는 TLS 사용 시 `rediss://`** URL을 제공할 수 있음. Celery broker_url 설정 시 **redis://·rediss://** 모두 대응하고, TLS(`rediss://`)일 때는 **ssl_cert_reqs=None** 등 옵션 적용해 연결 실패 방지. (로컬은 보통 `redis://`.)
- **영속성(AOF/RDB)·Railway Redis 플랜 확인**: Redis는 Celery **broker·알림 큐**로 사용되므로 재시작/장애 시 큐 유실을 막기 위해 **AOF(Append Only File)** 또는 **RDB** 백업이 켜져 있는지 확인. **Railway 무료/저가형 플랜**은 재시작 시 데이터가 날아가는 경우가 있으므로, 배포 전 **AOF 설정이 가능한 플랜인지** 반드시 확인. (ROADMAP "진행 시 예상 문제·대비" Redis 영속성 참고.)
- **visibility_timeout**: 크롤 태스크는 수 분~수십 분 걸릴 수 있음. `app/core/celery_app.py`에서 **broker_transport_options = {"visibility_timeout": 3600}**(1시간) 설정. 다중 워커 시 타임아웃보다 오래 걸리면 같은 메시지가 재전달될 수 있으므로 확인.
- **워커는 항상 `-O fair`로 기동**: Fair Scheduling으로 I/O Bound 크롤 태스크가 한 워커에 몰리지 않도록 함. prefetch는 `CELERY_WORKER_PREFETCH_MULTIPLIER`(기본 1)로 조정 가능.

### 3. 환경 변수 (Variables)

웹 서비스(및 워커 서비스) **Variables** 탭에서 추가. 새 변수 추가 시 `.env.example`도 함께 갱신.

| 변수 | 설명 | 적용 시점 |
|------|------|-----------|
| `APP_ENTRY` 또는 `ROLE` | 진입점. **필수(Fail-fast)**. `api`=웹 서비스(FastAPI), `celery`=워커/beat. 웹 서비스 Variables에 `api`, 워커 서비스 Variables에 `celery` 설정. | 모든 환경 |
| `SENTRY_DSN` | Sentry 에러 모니터링 DSN | 1단계~ |
| `DATABASE_URL` | **`postgresql+psycopg://...`** 권장. `postgres://`만 넣어도 앱이 `postgresql+psycopg://`로 자동 변환함. (구형 asyncpg 대신 psycopg 사용 — Railway 프록시 환경에서 안정적.) 2단계~. **비밀번호는 영문·숫자만** 사용. **시스템 환경변수가 .env보다 우선** → Windows에서 `echo $env:DATABASE_URL`로 확인 후, 프로젝트용이 아니면 제거. |
| `DB_CONNECT_RETRIES` | 연결 실패 시 재시도 횟수. 기본 5. | 2단계 (선택, Railway 권장) |
| `DB_CONNECT_RETRY_INTERVAL_SEC` | 재시도 간격(초). 기본 2. | 2단계 (선택) |
| `DB_POOL_SIZE_ASYNC` | Async API 풀 크기(프로세스당). 프로파일 R 기본 4. | 2단계 (선택, 용량 계획 참고) |
| `DB_POOL_MAX_OVERFLOW_ASYNC` | Async API 풀 오버플로(프로세스당). 프로파일 R 기본 6. | 2단계 (선택) |
| `DB_POOL_TIMEOUT_ASYNC` | Async 풀 대기 타임아웃(초). 운영 권장 5. | 2단계 (선택) |
| `DB_STATEMENT_TIMEOUT_MS` | SQL statement timeout(ms). 기본 30000(30초). | 2단계 (선택) |
| `DB_POOL_SIZE_SYNC` | Celery Sync 풀 크기(워커·자식당). 기본 2. | 3단계 (선택) |
| `DB_POOL_MAX_OVERFLOW_SYNC` | Celery Sync 풀 오버플로. 기본 0. | 3단계 (선택) |
| `DB_POOL_TIMEOUT_SYNC` | Sync 풀 대기 타임아웃(초). 기본 30. | 3단계 (선택) |
| `DB_POOL_RECYCLE_SYNC` | Sync 풀 유휴 연결 재활용 주기(초). 기본 300. -1이면 미설정. | 3단계 (선택) |
| `DB_MAX_CONNECTIONS` | DB max_connections(예산 검사용). 설정 시 부팅 시 Peak vs App_budget 검사. | 2단계 (선택) |
| `DB_RESERVED` | DB 예약 연결 수(슈퍼유저/관리). 기본 3. App_budget=(max-Reserved)×0.7. | 2단계 (선택) |
| `DB_POOL_STRICT_BUDGET` | True면 예산 초과 시 부팅 실패. 기본 False. | 2단계 (선택) |
| `DEPLOY_SURGE_FACTOR` | 롤링/스케일 시 피크 배수. 기본 2. | 2단계 (선택) |
| `DB_API_INSTANCES`, `DB_UVICORN_WORKERS`, `DB_WORKER_INSTANCES`, `DB_CELERY_CONCURRENCY` | 예산 검사용 인스턴스/워커 수. 기본 1. | 2단계 (선택) |
| `REDIS_URL` | Redis 연결 URL. Railway는 **rediss://**(TLS) 제공 가능. Celery broker가 rediss 시 SSL 옵션 적용. | 3단계~ |
| `REDIS_CELERY_URL` | Celery broker/result_backend 전용. 비어 있으면 REDIS_URL 사용. Celery만 별도 인스턴스 또는 DB 번호 분리 시 설정. | 3단계 (선택) |
| `CRAWL_TRIGGER_SECRET` | Cron이 POST /internal/trigger-crawl 호출 시 검증용 시크릿 (헤더 또는 쿼리로 전달) | 3단계 Cron 연동 시 |
| `AUTH_GOOGLE_RATE_LIMIT_PER_MINUTE` | 동일 IP 기준 `/v1/auth/google` 분당 최대 호출 수. 기본 10. | 2단계 Auth (선택) |
| `AUTH_REFRESH_RATE_LIMIT_PER_MINUTE` | 동일 IP 기준 `/v1/auth/refresh` 분당 최대 호출 수. 기본 60. | 2단계 Auth (선택) |
| `INTERNAL_TRIGGER_CRAWL_RATE_LIMIT_PER_MINUTE` | 동일 IP 기준 `/internal/trigger-crawl` 분당 최대 호출 수. 기본 10. | 3단계 Cron 연동 시 (선택) |
| `INTERNAL_CRAWL_STATS_RATE_LIMIT_PER_MINUTE` | 동일 IP 기준 `/internal/crawl-stats` 분당 최대 호출 수. 기본 30. | 3단계 운영 모니터링 (선택) |
| `TRUSTED_PROXY_IPS` | 역방향 프록시(예: Railway) 직전 피어 IP를 쉼표 구분으로 설정. 비어 있으면 `X-Forwarded-For`를 신뢰하지 않고 `request.client.host`만 사용. **프로덕션에서는 비어 있으면 부팅 실패(Fail-fast)**. Railway 등 배포 시 반드시 설정. | 2단계~ (리버스 프록시 사용 시) |
| `TRUSTED_PROXY_SKIP_FAST` | `1`이면 프로덕션에서 TRUSTED_PROXY_IPS 비어 있어도 부팅 허용. **프록시 뒤에 두지 않는 프로덕션만** 사용. 기본 0. | 선택 (프록시 미사용 프로덕션만) |
| `POLITE_DELAY_SECONDS` | 요청/페이지 간 최소 딜레이(초). 대상 서버 부하·IP 차단 완화. 기본 1. 단과대별 오버라이드는 DB 메타데이터 테이블 또는 ConfigMap/리로드 가능 소스로 설계(재시작 없이 변경 가능). | 3단계 (선택) |
| `CELERY_WORKER_PREFETCH_MULTIPLIER` | 워커 prefetch 배수. 기본 1. 짧은 태스크 많으면 2~4로 조정. **-O fair**와 함께 사용. | 3단계 (선택) |
| `JWT_SECRET` | JWT 서명용 비밀키 (강한 랜덤 문자열). RS256 사용 시 불필요. | 2단계 Auth 후 (HS256 시) |
| `JWT_PRIVATE_KEY_PEM` | JWT RS256 개인키 PEM(한 줄로 `\n` 포함 가능). RS256 사용 시 `JWT_PUBLIC_KEY_PEM`과 쌍으로 필수. | 2단계 Auth (RS256 선택 시) |
| `JWT_PUBLIC_KEY_PEM` | JWT RS256 공개키 PEM. 검증 서비스는 공개키만 보유하면 됨. | 2단계 Auth (RS256 선택 시) |
| `JWT_ACCESS_EXPIRE_SECONDS` | Access 토큰 만료(초). 기본 600(10분). 탈퇴/탈취 시 노출 시간 최소화. | 2단계 (선택) |
| `REDIS_BLOCKLIST_FAIL_CLOSED` | Redis 장애 시 True=인증 거부(Fail-Closed), False=서명만 검증 후 통과(Fail-Open). 멀티 인스턴스·방어력 유지 시 true 권장. 기본 False. | 2단계 Auth (Blocklist 사용 시) |
| `API_RATE_LIMIT_REQUIRE_REDIS` | True면 Redis 미설정/장애 시 레이트리밋 검사 대신 503. 멀티 인스턴스 운영 시 true 권장(Redis 없으면 인메모리 fallback만 되어 인스턴스별로만 적용됨). 기본 False. | 2단계 Auth·Internal API |
| `REDIS_BLOCKLIST_CIRCUIT_FAILURE_THRESHOLD` | Blocklist Circuit Breaker: 연속 실패 N회 시 열림. 기본 3. | 2단계 (선택) |
| `REDIS_BLOCKLIST_CIRCUIT_OPEN_SECONDS` | Circuit 열림 유지 시간(초). 기본 60. | 2단계 (선택) |
| `REDIS_BLOCKLIST_CIRCUIT_HALF_OPEN_INTERVAL_SECONDS` | Half-open 시도 간격(초). 기본 15. | 2단계 (선택) |
| `REDIS_TRIGGER_LOCK_REQUIRED` | True면 Redis 미설정/실패 시 trigger-crawl 503. 운영 권장 True. 기본 True. | 3단계 (선택) |
| `REDIS_BLOCKLIST_MAX_CONNECTIONS` | Blocklist용 Redis 비동기 풀 크기. Uvicorn 동시 처리량에 맞게. 기본 20. | 2단계 Auth (Blocklist 사용 시) |
| `JWT_REFRESH_EXPIRE_DAYS` | Refresh 토큰 만료(일). 기본 7. | 2단계 (선택) |
| `GOOGLE_CLIENT_ID` | 구글 OAuth 2.0 클라이언트 ID | 2단계 Auth (구글 먼저) |
| `GOOGLE_CLIENT_SECRET` | 구글 OAuth 2.0 클라이언트 시크릿 | 2단계 Auth |
| `ALLOWED_ORIGINS` | 프론트 도메인. **JSON 배열**(`["https://app.example.com"]`) 또는 **쉼표 구분(CSV)** 지원. `*`는 허용하지 않으며, allow_credentials=True + 명시 오리진만 허용. | 6단계 연동 시 |
| `STRICT_STARTUP_DB_CHECK` | `true`(기본): DB 연결 실패 시 부팅 중단. `false`: soft-start(기동은 하고 readiness에서 차단). | 선택 |
| `ENVIRONMENT` | `production` \| `staging` \| `development`. production 시 스토리지 s3 강제. | 선택 |
| `CONTENT_STORAGE_TYPE` | `s3` \| `local`. **production에서는 s3 필수.** | 본문 스토리지 사용 시 |
| `S3_BUCKET` | S3 버킷 이름. production + s3 시 필수. | 본문 스토리지 S3 시 |
| `S3_SSE_KMS_KEY_ID` | S3 SSE-KMS 키 ID. 설정 시 업로드 시 `ServerSideEncryption=aws:kms`, `SSEKMSKeyId` 적용. 미설정 시 기본 KMS 키 사용. | S3 암호화 시 |
| `CONTENT_UPLOAD_FAILURE_POLICY` | `allow_none`: 업로드 실패 시 None 반환(크롤 계속). `fail`: 예외 전파(데이터 유실 방지). production에서는 `fail` 필수. | 선택 |
| 기타 | Gemini API 키 등 | 해당 기능 단계 |

(나중에 카카오 등 추가 시 `KAKAO_CLIENT_ID` 등 동일 방식으로 Variables + `.env.example`에 추가.)

**Rate limit 및 리버스 프록시**  
Railway 등 리버스 프록시 뒤에 배포할 때 `TRUSTED_PROXY_IPS`를 설정하지 않으면, 앱이 받는 TCP 연결의 직전 피어는 프록시 IP 하나뿐이므로 `request.client.host`가 모두 동일하게 됩니다. 이 경우 **동일 IP 기준 Rate Limit**(Auth·Internal API 등)이 한 사용자만 초과해도 **전체 사용자가 차단**되는 Fail-closed가 발생할 수 있습니다. 프로덕션에서 프록시를 사용한다면 `TRUSTED_PROXY_IPS`에 프록시(또는 로드밸런서) IP를 쉼표 구분으로 넣어 `X-Forwarded-For`를 신뢰하도록 설정하세요.

**JWT RS256 (선택)**  
마이크로서비스 확장 시 토큰 검증 서비스가 시크릿 없이 공개키만으로 검증하려면 RS256 사용. 키 생성 예:

```bash
openssl genrsa -out private.pem 2048
openssl rsa -in private.pem -pubout -out public.pem
```

Private Key 내용을 `JWT_PRIVATE_KEY_PEM`, Public Key 내용을 `JWT_PUBLIC_KEY_PEM`에 설정(PEM 전체를 한 줄로 넣을 때 줄바꿈은 `\n`). 둘 다 설정되면 앱은 RS256으로 발급·검증하고, `JWT_SECRET`은 불필요. 자세한 결정 배경은 [docs/decisions/jwt-rs256.md](decisions/jwt-rs256.md) 참고.

**트러블슈팅: `password authentication failed for user "postgres"`**

- 이 메시지는 **앱이 사용하는 `DATABASE_URL`의 user/비밀번호가 Railway PostgreSQL과 일치하지 않을 때** 발생한다.
- **확인 1 — 변수 이름:** 웹 서비스 Variables에 **이름이 정확히 `DATABASE_URL`** 인지 확인. (`DATABASE_PUBLIC_URL` 등 다른 이름이면 앱이 읽지 않음.)
- **확인 2 — 변수 참조 사용 시:**  
  값이 `${{Postgres.DATABASE_URL}}`(또는 `${{PostgreSQL.DATABASE_URL}}` 등 **내부 URL 변수**)인지 확인.  
  **`${{Postgres.DATABASE_PUBLIC_URL}}`로 되어 있으면 공개 URL이 주입되어 내부에서 인증 실패가 날 수 있음.** → 참조를 **내부 URL**(Postgres 서비스의 `DATABASE_URL`)로 바꾼 뒤 재배포.
- **확인 3 — 직접 입력 시:**  
  Railway **PostgreSQL 서비스** → **Variables** 또는 **Connect** 탭에서 **내부 연결 URL**(호스트 `postgres.railway.internal`) 전체를 복사해 웹 서비스 `DATABASE_URL`에 넣고, 스킴만 **`postgresql+psycopg://`** 로 변경. (앱이 `postgres://`를 자동으로 `postgresql+psycopg://`로 바꿔 주므로 그대로 넣어도 됨.) 비밀번호에 `@`, `#`, `%` 등이 있으면 퍼센트 인코딩 필요.
- 로컬용·예시용 URL(`postgres:postgres` 등)을 넣으면 이 오류가 난다. **반드시 Railway Postgres 서비스에 나온 값 또는 내부 URL 변수 참조를 사용**한다.
- **다른 원인 (변수·URL이 맞는데도 실패할 때):**
  - **참조 서비스 이름 불일치:** `${{Postgres.DATABASE_URL}}`에서 **Postgres**는 대시보드에 보이는 **PostgreSQL 서비스 이름**과 정확히 같아야 한다. (예: 서비스 이름이 `PostgreSQL`이면 `${{PostgreSQL.DATABASE_URL}}`.) 참조가 해석되지 않으면 빈 값이나 잘못된 값이 들어갈 수 있다.
  - **비밀번호 재설정:** Railway PostgreSQL 서비스에서 **Settings → Reset database password** 후, 웹 서비스 Variables의 `DATABASE_URL`을 **새 내부 URL**로 다시 설정(참조면 참조 유지, 직접 입력이면 새 URL 복사 후 스킴만 `postgresql+asyncpg://`로 변경).
  - **공개 URL로 시도:** 일부 환경에서는 내부 URL 대신 **공개 URL** 참조(`${{Postgres.DATABASE_PUBLIC_URL}}`)로 연결되는 경우가 있다. 내부로만 실패하면 한 번 시도해 볼 것.
  - **실제 사용 값 확인:** 앱 기동 시 로그에 `DB connect: host=... port=... dbname=... user_set=... password_set=...`가 찍힌다. `password_set=False`이면 URL 파싱 시 비밀번호가 빠진 것(특수문자 미인코딩 등)일 수 있다. `host`가 `postgres.railway.internal`이면 내부 URL이 쓰인 것이고, 다른 호스트면 다른 URL이 주입된 것이다.

**트러블슈팅: `connection timeout expired` (Alembic / Postgres)**

- **원인:** 배포 시 Start Command에서 `alembic upgrade head`가 실행되는데, 그 시점에 **PostgreSQL이 아직 준비되지 않았을 때** 발생한다. (Railway에서 웹 서비스와 DB가 동시에 올라오거나, DB가 슬립에서 깨어나는 동안 연결 시도가 기본 타임아웃 내에 실패.)
- **조치:**  
  1. **코드 반영 여부:** 이 프로젝트의 `alembic/env.py`에는 **연결 타임아웃 90초**와 **최대 6회 재시도(지수 백오프)**가 들어 있어, 대부분의 콜드스타트는 재배포만으로 해소된다. 최신 코드로 재배포한 뒤 다시 시도.  
  2. **여전히 실패할 때:** 웹 서비스 Variables에 아래를 추가해 타임아웃·재시도를 늘린다.  
     - `ALEMBIC_CONNECT_TIMEOUT` = `120` (연결 1회당 대기 초, 기본 90)  
     - `ALEMBIC_RETRY_ATTEMPTS` = `8` (재시도 횟수, 기본 6)  
     - `ALEMBIC_RETRY_INITIAL_SEC` = `10` (첫 재시도 전 대기 초, 기본 8)  
     - `ALEMBIC_RETRY_MAX_SEC` = `60` (재시도 간 최대 대기 초, 기본 40)  
  3. **DATABASE_URL 확인:** 내부 URL(`postgres.railway.internal`)을 쓰는지 확인. 공개 URL만 쓰면 레이턴시/방화벽으로 타임아웃이 날 수 있음. 위 **트러블슈팅: password authentication failed** 항목의 변수 참조·내부 URL 설명 참고.  
  4. **내부 URL이 계속 타임아웃될 때:** Railway에서 내부 호스트로 연결이 안 되면, **마이그레이션만** 공개 URL로 실행하도록 웹 서비스 Variables에 **`ALEMBIC_DATABASE_URL`** = `${{Postgres.DATABASE_PUBLIC_URL}}` 를 추가한다. (앱 런타임은 기존대로 `DATABASE_URL`=내부 URL 사용. 마이그레이션 시에만 `ALEMBIC_DATABASE_URL`이 있으면 그걸 쓴다.) 스킴은 **`postgresql+psycopg://`** 또는 `postgresql://` 이어야 하며, 공개 URL이 `postgres://` 이면 앱/마이그레이션이 자동으로 `postgresql+psycopg://`로 정규화한다.

**트러블슈팅: `Can't locate revision identified by '011'` (Alembic)**

- **원인:** DB의 `alembic_version` 테이블에는 리비전 `011`이 기록되어 있는데, **배포된 코드(main 등)에 해당 마이그레이션 파일이 없을 때** 발생한다. (예: 로컬/다른 브랜치에서 `alembic upgrade head`로 011까지 적용한 뒤, 011이 없는 브랜치로 배포.)
- **조치:**  
  1. **리비전 011 파일이 포함된 브랜치를 main에 머지**한 뒤 푸시하여 재배포한다. (`alembic/versions/011_add_crawl_runs_celery_task_id_unique.py` 등이 main에 있어야 함.)  
  2. 또는 DB를 011 이전으로 되돌리고 싶다면, **로컬에서** 공개 DB URL로 `alembic downgrade 010` 실행 후, 그 다음 main으로 배포한다. (011에서 추가된 스키마/인덱스가 있다면 수동 정리 필요.)
- **원칙:** 배포 브랜치에 포함된 마이그레이션 파일이 DB에 기록된 리비전과 일치해야 한다.

**크롤 운영 정책:** FastAPI 내 크롤 트리거(POST /internal/trigger-crawl 또는 동기 호출)는 **개발·소량 테스트용**이다. **프로덕션 정기 크롤은 Celery 워커만 사용**한다. Cron이 6시간마다 trigger-crawl을 호출하면 Celery 태스크가 enqueue되고 워커가 실행한다.

**첨부파일 저장 원칙:** 첨부파일은 **원격 URL(또는 파일명) 리스트만** DB(Notice.attachments JSONB)에 보관한다. **로컬 파일시스템에 다운로드·저장하지 않는다.** (Railway 등 컨테이너는 휘발성 파일시스템이므로 재시작 시 파일이 사라진다.) 클라이언트가 직접 원본 URL로 다운로드하거나, 백엔드를 거칠 경우 **S3 등 외부 오브젝트 스토리지**로 업로드하는 파이프라인만 사용한다.

**본문 스토리지(production):** `ENVIRONMENT=production`이면 **CONTENT_STORAGE_TYPE=s3**, **S3_BUCKET** 설정 필수. `local`은 dev/test만 허용. **CONTENT_UPLOAD_FAILURE_POLICY**: production에서는 `fail` 필수(업로드 실패 시 예외 전파, 데이터 유실 방지). **S3 암호화:** 업로드 시 `ServerSideEncryption=aws:kms` 적용. `S3_SSE_KMS_KEY_ID` 설정 시 해당 KMS 키 사용. **버킷 보안:** S3 버킷은 **퍼블릭 액세스 차단(Block all public access)** 을 반드시 적용하고, 본문 URL 접근은 서명된 URL 또는 앱 경유로만 제공할 것(규제/보안 감사 대비).

**DB 부팅·Liveness/Readiness:** `STRICT_STARTUP_DB_CHECK=true`(기본)면 DB 연결 실패 시 부팅 중단. `false`면 soft-start: 기동은 하고 **readiness**(`/ready`)가 실패해 DB 의존 API에 트래픽이 가지 않도록 인그레스/프로브에서 제어. 플랫폼 프로브는 **/health** 사용(DB/Redis 미체크로 장애 전파 완화). 상세는 [헬스체크·장애 전파 방지](#헬스체크장애-전파-방지) 참고.

### 4. 빌드·실행 설정

**웹 서버 (1~2단계, Nixpacks)**

- **Settings → Build**: Builder **Nixpacks** 유지.
- **Settings → Deploy** → **Start Command**:
  - `nixpacks.toml`에 마이그레이션 자동 실행 + 앱 시작 포함. Start Command를 **비워 두면** 이 설정 사용.
  - 커스텀 Start Command 사용 시: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Variables**: 웹 서비스에 **APP_ENTRY=api**(또는 ROLE=api) 반드시 설정.

**Playwright Celery 워커 (3단계~, Dockerfile 필수)**

- **새 서비스** 추가. 같은 repo 사용, **Dockerfile**로 빌드.
- **Settings → Build**: Builder **Dockerfile** 선택. 경로 예: `./Dockerfile.worker` 또는 `./Dockerfile`.
- **Settings → Deploy** → **Start Command**: `celery -A app.core.celery_app:app worker -l info -O fair -Q critical,crawl,ai --concurrency=1`  
  **라우팅 도입 후 워커는 소비할 큐를 반드시 명시해야 함.** 단일 워커는 `-Q critical,crawl,ai`로 3개 큐 모두 소비. 큐별 분리 시 예: `-Q crawl -c 2`, `-Q ai -c 1`. (OOM 방지: 동시 브라우저 개수 제한. **-O fair** 필수.)  
  Linux에서는 기본 `--pool=prefork`. Windows는 `--pool=solo` 필수. 연결 수는 [DB 연결 수 및 용량 계획](#db-연결-수-및-용량-계획) 참고.
- **Variables**: 워커 서비스에 **APP_ENTRY=celery**(또는 ROLE=celery) 반드시 설정.
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
