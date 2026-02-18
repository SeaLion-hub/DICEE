# DICEE 개발 로드맵

## 목차

- [지금 상태](#지금-상태)
- [확정 사항 (코드·문서 기준)](#확정-사항-코드문서-기준)
- [미리 결정 필요 (진입 전)](#미리-결정-필요-진입-전)
- [단계별 목표 기간](#단계별-목표-기간)
- [1단계: 비동기 백엔드 뼈대 구축 및 Railway 개통](#1단계-비동기-백엔드-뼈대-구축-및-railway-개통)
- [2단계: 비동기 DB(PostgreSQL) 및 ORM·Auth 설계](#2단계-비동기-dbpostgresql-및-ormauth-설계)
- [3단계: Playwright 자체 크롤러 및 작업 큐 연동](#3단계-playwright-자체-크롤러-및-작업-큐-연동)
- [4단계: 티어링 기반 Multimodal AI 파이프라인](#4단계-티어링-기반-multimodal-ai-파이프라인)
- [5단계: 검색·프로필 매칭 API 완성](#5단계-검색프로필-매칭-api-완성)
- [6단계: Next.js 프론트 연동 및 최종 런칭](#6단계-nextjs-프론트-연동-및-최종-런칭)
- [추가 검토 아이디어](#추가-검토-아이디어)

---

## 작성 규칙 (이 문서)

- **단계별 구조**: 각 단계는 `목표` → `할 일` → `검증`(해당 시) → `마일스톤` 순으로 작성한다.
- **할 일**: 한 항목당 한 주제. 하위 내용은 들여쓰기 리스트로 구분한다.
- **수정 시**: 로드맵 본문을 바꿀 때는 **날짜**, **수정 내용**, **이유**를 WORK_LOG 또는 본문 하단에 기록한다.
- **추가 아이디어**: 새로 떠오른 기능·변경은 "추가 검토 아이디어"에만 적고, 현재 단계가 끝날 때까지 단계 본문은 유지한다.
- **추가 검토 아이디어 작성**: 각 아이디어는 **고려 시점**을 반드시 명시한다. 예: "고려 시점: 3단계 이후", "고려 시점: 5단계", "고려 시점: 6단계 이전". 해당 단계에서 검토할지, 그 이전/이후인지 한눈에 보이게 한다.
- **단계 완료 시 확인**: 어떤 단계가 끝나면(마일스톤 달성), 작업자(또는 에이전트)는 **그 단계 또는 그 이전 단계**에 해당하는 추가 검토 아이디어에 대해 사용자에게 검토 여부를 물어본다. 예: 3단계 완료 시 → 고려 시점이 1·2·3단계인 아이디어를 정리해 "이 중 어떤 걸 다음 단계에 반영할지/미룰지 결정할까요?"라고 확인 요청.

---

## 지금 상태

| 항목 | 내용 |
|------|------|
| **현재 단계** | **3단계 진행 중** (Playwright 자체 크롤러 및 작업 큐 연동) |
| **이번 목표** | Celery·Redis 연동 완료, 크롤러 Repository 분리·upsert·content_hash, trigger-crawl API, Railway Dockerfile 워커, Sentry 워커 부착 |
| **3단계 구현 현황** | 아래 [3단계 구현 현황](#3단계-구현-현황-진행-중) 표 참고. (완료/미완료·규칙 준수 여부) |
| **작업 기록** | [WORK_LOG.md](./WORK_LOG.md) |
| **배포** | 백엔드 Railway, 프론트 Vercel. 상세는 [DEPLOYMENT.md](./DEPLOYMENT.md). 프론트 폴더는 **6단계에서** 생성. |
| **주의사항** | 바이브 코딩 시 실수 방지: [CAUTIONS.md](./CAUTIONS.md) |

---

## 확정 사항 (코드·문서 기준)

이미 코드·문서에서 확정된 사항. "2단계에서 결정" 등 본문 표현이 있어도 여기 한곳만 보면 된다.

| 구분 | 확정 내용 |
|------|-----------|
| **데이터 구조** | Raw vs 정제: **같은 테이블(Notice)에 단계별 컬럼**(raw_html → ai_extracted_json). 별도 Raw 테이블 없음. |
| **일정 저장** | **Notice 컬럼**(deadline, event_start, event_end, event_title). 공지-일정 1:N 테이블 없음. |
| **OAuth 토큰** | **응답 body JSON**으로 Access/Refresh JWT 반환. Set-Cookie 미사용. 프론트는 Authorization 헤더. (DEPLOYMENT·코드 일치) |
| **3단계** | 공지 유니크 `(college_id, external_id)`. 스케줄러: Railway Cron + POST /internal/trigger-crawl. Celery Beat 미사용(비용). |
| **4단계** | 입출력·자격요건 Pydantic 필드·rate_limit='10/m' (기존 "단계별 결정 사항 반영"과 동일). |
| **5단계** | GET /v1/calendar/events?year=&month=, 응답 두 배열. user_calendar_events UniqueConstraint(user_id, notice_id). |
| **6단계 달력 UX** | **한 화면 통합 + 시각적 구분 + 토글 필터**. 탭 분리 비권장(일정 충돌 확인이 달력 본질). 상세는 6단계 "달력 표시 방식 (6단계 진입 전 확정)" 참고. |

---

## 미리 결정 필요 (진입 전)

각 단계 진입 전 또는 해당 단계 설계 시 결정해야 할 사항. 미리 정하지 않으면 리워크·혼란이 발생할 수 있음.

| 단계 | 항목 | 결정 시점 | 설명 |
|------|------|-----------|------|
| 3단계 | College 목록·external_id | 3단계 시작 전 | 수집할 단과대/게시판 목록, College.external_id(소스 식별자) 정의. 크롤러 모듈·시드 데이터 설계에 직결. |
| 3단계 | Notice.external_id 추출 규칙 | 3단계 시작 전 | 게시판별 공지 고유 ID 추출 방식(게시글 번호, URL 경로 등). 사이트마다 다르므로 소스별 규칙 문서화. |
| 3단계 | 크롤 주기 | 3단계 Cron 설정 시 | 1시간마다 / 6시간마다 등. 비용·데이터 최신성 균형. |
| 4단계 | Notice 일정 스키마 정합성 | 4단계 진입 전 | 현재: dates·eligibility(JSONB). 로드맵 5단계: deadline, event_start, event_end, event_title. 복원할지, dates/eligibility를 API에서 매핑할지 결정. |
| 4단계 | User↔AI 매칭 규칙 | 4단계 스키마 설계 시 | User.profile_json(major, grade 등)와 ai_extracted_json(target_departments, target_grades)의 매칭 로직. "포함 여부" vs "정확 일치". |
| 4단계 | 학과·학년 값 형식 | 4단계 스키마 설계 시 | target_departments, target_grades 값 범위·형식 통일. User 프로필 값과 비교 가능하도록. (예: "전기전자공학부" vs "컴퓨터공학" 매핑) |
| 5단계 | 목록 API 페이지네이션 | 5단계 API 설계 시 | cursor vs offset, 기본 page_size. 6단계 무한 스크롤 설계에 영향. |
| 5단계 | 일정 API 필터 범위 | 5단계 API 설계 시 | year, month 외 day 또는 from/to 필요 여부. 6단계 주간 뷰 등에 영향. |

---

## 단계별 목표 기간

| 단계 | 목표 기간(주) | 비고 |
|------|----------------|------|
| 1단계 | 완료 | — |
| 2단계 | 완료 | — |
| 3단계 | (비움 또는 TBD) | 3단계 시작 시 대략적 기간 설정 권장. 지연 시 WORK_LOG에 사유 |
| 4단계 | (비움 또는 TBD) | 동일 |
| 5단계 | (비움 또는 TBD) | 동일 |
| 6단계 | (비움 또는 TBD) | 동일 |

---

## 1단계: 비동기 백엔드 뼈대 구축 및 Railway 개통

### 목표

단일 파일 의존 구조를 버리고, 계층형 아키텍처를 세운 뒤 Railway에 빈 서버를 배포한다.

### 할 일

- **진입점·패키지 구조 (고정)**
  - 진입점: `app.main:app`. 루트에 `app/` 패키지, 그 안에 `api/`, `core/`, `services/`, `repositories/`, `models/`, `schemas/` 배치.
  - DEPLOYMENT의 Start Command와 일치시켜 두고, 폴더 추가 시에도 이 구조 유지.

- **의존성·환경**
  - 배포용: `requirements.txt`에 버전 고정(pip-tools 권장). 테스트/린트용은 `requirements-dev.txt` 분리. CI/배포는 `requirements.txt`만 사용.
  - 가상환경 세팅. `fastapi`, `uvicorn`, `sqlalchemy`, `alembic`, `asyncpg` 등 버전 고정.

- **계층형 디렉터리**
  - `api/`: 라우팅.
  - `services/`: 비즈니스 로직.
  - `repositories/`: DB 접근.
  - `models/`: DB 스키마.
  - `schemas/`: 검증.
  - `core/`: 설정·의존성.

- **설정·시크릿 원칙**
  - 모든 설정은 환경변수. `.env.example`에 **키 이름만** 나열(값 제외).
  - 커밋 전 `.env` 실수 커밋 방지(pre-commit 또는 스크립트). 새 변수 추가 시 DEPLOYMENT 표 + `.env.example` 동시 갱신.

- **에러·로깅 정책**
  - 공통 예외 핸들러: 비즈니스 예외 → HTTPException, 그 외 → 500 + 로그. `except Exception` 남용 금지.
  - 로깅 형식(구조화 로그 등) 1단계에서 한 번 정함.

- **모니터링 (Sentry)**
  - **1단계에서** Sentry DSN만 환경변수로 넣고, 백엔드 예외 발생 시 바로 슬랙/이메일 알림 받을 수 있게 세팅. 3·4단계에서 에러가 많이 나므로 미리 인프라만 갖춰 둠.

- **Railway CI/CD**
  - GitHub 푸시 시 자동 빌드·배포. Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
  - 3단계 Playwright 워커는 **Nixpacks 대신 Dockerfile** 사용 예정. 1단계 웹 서버는 Nixpacks로 충분.

### 검증 (변동 대비)

- 마일스톤 달성 시 **자동 검증** 추가: `GET /health` → 200 확인하는 스크립트를 CI(GitHub Actions 등)에 넣기.

### 마일스톤

Railway 도메인으로 `GET /health` 호출 시 `200` + `{"status":"ok"}`.

---

## 2단계: 비동기 DB(PostgreSQL) 및 ORM·Auth 설계

### 목표

문자열 SQL에서 벗어나 ORM으로 안전하게 데이터를 다루고, **유저 인증/인가 설계를 확정**한다.

### 할 일

- **환경 정책**
  - 로컬: `DATABASE_URL`로 로컬(또는 Docker) PostgreSQL 사용.
  - Railway: 배포 시 마이그레이션 실행 방식(배포 스크립트에서 `alembic upgrade head` vs 수동 1회) 정해 두기. 마이그레이션은 **항상 순서대로, up만** 적용.

- **Railway DB**
  - PostgreSQL 추가 후, 연결 URL을 `postgresql+asyncpg://` 형태로 환경변수 등록.

- **비동기 ORM**
  - SQLAlchemy 2.0으로 `Notice`, `College`, `User` 정의. AI 추출 자격 요건은 JSONB.
  - **Raw vs 정제 데이터**: **확정**: 같은 테이블(Notice)에 단계별 컬럼(raw_html → ai_extracted_json). (위 확정 사항 참고.)
  - **일정·달력 대비**: **확정**: Notice에 일정 컬럼(deadline, event_start, event_end, event_title). user_calendar_events는 2단계에서 정의. (위 확정 사항 참고.)
  - **본문 해시·수동 수정 플래그**: `content_hash`(제목+본문 해시값, 3·4단계 변경 감지용), `is_manual_edited`(관리자 수동 수정 여부, AI 재덮어쓰기 방지·어드민 확장용)를 Notice에 미리 설계.

- **Auth 도메인 (필수)**
  - **구글 로그인(OAuth) 먼저** 구현. JWT 발급. (자체 이메일/비밀번호 가입은 선택.)
  - **구글 ID 토큰 서명 검증**: 베타 전 `google-auth`의 `verify_oauth2_token` 또는 JWKS 검증 적용. `verify_signature=False` 금지.
  - `User`: `provider`(예: `google`), `provider_user_id`, 프로필 필드(전공, 학년, 군필, 학점 등). **다중 OAuth 제공자** 전제 스키마로 설계해, 나중에 카카오 등 추가 시 동일 스키마로 확장. OAuth 전용이면 비밀번호 해시 생략.
  - 5단계 "유저 프로필 기반 매칭"은 로그인한 유저 전제이므로, 2단계에서 Auth·User 구조 확정.
  - **OAuth 핸드쉐이크 (2·6단계 연계, 필수)**  
    - **확정**: 응답 body JSON으로 Access/Refresh JWT 반환. 프론트는 Authorization 헤더. (위 확정 사항·DEPLOYMENT 참고.)
    - 프론트(Next.js)에서 구글 OAuth 후 **Authorization Code**를 받아 **백엔드 `/v1/auth/google`로 전달** → 백엔드가 구글에 code 검증 후 자체 JWT 발급 → JSON body로 반환. CORS·Credentials 정책을 이에 맞춰 설계. (6단계에서 CORS·보안 이슈 방지.)

- **Alembic**
  - 코드로 정의한 테이블을 Railway DB에 반영하는 마이그레이션 세팅.

### 검증

- 앱 부팅 + `select(1)` 또는 마이그레이션 적용 성공을 CI에서 확인 가능하면 추가.

### 마일스톤

DB 클라이언트로 테이블 확인 가능. 앱 부팅 시 연결 검증. Auth 방식(구글 OAuth + JWT)과 User 스키마 문서화 완료.

---

## 3단계: Playwright 자체 크롤러 및 작업 큐 연동

### 목표

Apify 의존을 줄이고, 백그라운드에서 공지를 수집하는 자체 엔진을 완성한다.

### 3단계 구현 현황 (진행 중)

아래 표는 **할 일** 항목별로 코드·인프라 기준 구현 여부를 정리한 것. 규칙(계층 분리, CAUTIONS) 준수 여부 포함.

| 할 일 항목 | 구현 여부 | 비고 (파일·규칙 준수) |
|------------|-----------|------------------------|
| **Celery & Redis** | | |
| └ Redis 연결 설정 | ✅ | `app/core/config.py`에 `redis_url` (또는 `REDIS_URL`) 환경변수. `.env.example`에 REDIS_URL·CRAWL_TRIGGER_SECRET. |
| └ Celery 앱 진입점(broker) | ❌ | `app/worker.py` 등 Celery 앱 생성·broker=Redis 설정 **미구현**. `shared_task`만 정의된 상태. |
| └ Celery 크롤 태스크 정의 | ✅ | `app/services/tasks.py`: `crawl_college_task(college_code)`, 내부 `asyncio.run(run_crawler_async)`. integrations.mdc(동기 def + asyncio.run) 준수. |
| **데이터 소스·수집 방식** | | |
| └ httpx 우선(API 역공학) | ✅ | 공대 크롤러는 **httpx + BeautifulSoup** 사용. Playwright 미사용(해당 게시판은 정적 HTML). |
| └ 사이트별 크롤러 모듈 분리 | ✅ | `app/services/crawlers/yonsei_engineering.py`. config로 `engineering` URL·선택자 분리. |
| **크롤러 설정(config) 분리** | ✅ | `app/core/crawler_config.py`: 사이트별 `url`, `selectors.row`, `selectors.link` 등. 코드 하드코딩 최소화. |
| **수집 대상·데이터** | | |
| └ 제목·본문·이미지 URL/Base64·첨부 | ✅ | `yonsei_engineering.py`에서 제목, 본문(raw_html), images(URL+Base64), attachments 수집 후 Notice 저장. |
| └ 포스터 이미지 원본 URL | ⚠️ | `images` JSONB에 URL/Base64 저장. 별도 `poster_image_url` 컬럼은 005 마이그레이션에서 제거됨. 4단계 Multimodal 시 첫 이미지 또는 poster 전용 필드 복원 검토. |
| **데이터 정합성** | | |
| └ 공지 유니크 (college_id, external_id) | ✅ | Notice에 `UniqueConstraint("college_id", "external_id")`. 크롤러에서 동일 조합 존재 시 **스킵**(신규만 insert). |
| └ upsert(재수집 시 갱신) | ❌ | 현재는 **존재하면 스킵**만 구현. **upsert**(있으면 update, 없으면 insert) 미구현. 로드맵 요구사항. |
| └ content_hash 저장·변경 감지 | ❌ | Notice 모델에 `content_hash` 컬럼 있음. 크롤러에서 **해시 계산·저장** 및 **해시 변경 시에만 4단계 큐 enqueue** 로직 미구현. |
| └ 특정 기간/소스 재수집·복구 절차 | ❌ | 스크립트 또는 절차 미정리. |
| **아키텍처 규칙(architecture.mdc)** | | |
| └ DB 접근은 repositories만 | ❌ | 크롤러가 `services/crawlers`에서 직접 `select(College)`, `select(Notice)`, `session.add(Notice)` 수행. **Repository 레이어**로 분리 필요. |
| **Railway Playwright 워커** | | |
| └ Dockerfile (Chromium 설치) | ❌ | Dockerfile·Dockerfile.worker **미구현**. Nixpacks는 Chromium 미설치. Playwright 필요 시 Dockerfile 필수. |
| └ OOM 방지 옵션·concurrency | — | 워커 진입점 없어 미적용. 구현 시 `--no-sandbox`, `--disable-dev-shm-usage`, `--concurrency=1` 적용. |
| **재시도·스케줄링** | | |
| └ Celery autoretry_for | ⚠️ | 태스크에 `autoretry_for` 미명시. 추가 권장. |
| └ POST /internal/trigger-crawl | ❌ | FastAPI 엔드포인트 **미구현**. 보안 키 검증 후 Celery 태스크 enqueue 필요. |
| **모니터링** | | |
| └ Sentry 워커 부착 | ❌ | 워커 프로세스 진입점 없음. 구현 시 worker 초기화 단계에서 Sentry 설정. |

**Notice 스키마 정합성 (4·5단계와 맞추기)**  
- 현재 DB/모델: `dates`, `eligibility`(JSONB), `images`, `attachments`. 005 마이그레이션에서 `deadline`, `event_start`, `event_end`, `event_title`, `poster_image_url` 제거됨.  
- 로드맵 확정: 5단계 일정 API는 **deadline, event_start, event_end, event_title** 컬럼 또는 이에 대응하는 구조 전제.  
- **4단계 진입 전**에 `dates`/`eligibility`를 그대로 쓸지, **deadline/event_* 복원**할지, 또는 API 계층에서 `dates` JSON을 deadline/event_* 형태로 매핑할지 결정 필요. (미리 결정 필요 표에 4단계 항목으로 넣어 둠.)

### 할 일 (상세)

- **Celery & Redis**
  - Railway에 Redis 추가. **Celery 앱 진입점**(예: `app/worker.py`)에서 broker=Redis, result backend 설정. Celery로 크롤링 전용 워커 구동. FastAPI(비동기)와 Celery(동기) 역할 분리.
  - AI 호출 태스크는 4단계에서 **rate_limit** 적용(아래 4단계 참고).

- **데이터 소스·수집 방식 (사전 조사 필수)**
  - 크롤 전 타겟 게시판에서 **내부 API(XHR/Fetch)** 존재 여부를 개발자 도구 Network 탭으로 확인. 가능한 소스는 **httpx**로 직접 호출 → 메모리·속도 절감. **Playwright는 JS 렌더링이 반드시 필요한** 극소수 페이지만 사용.
  - 사이트마다 크롤러 모듈 분리(예: `crawlers/portal_yonsei.py`, `crawlers/yonsei_engineering.py`).

- **크롤러 설정(config) 분리**
  - CSS 선택자(제목, 날짜, 본문 등)·URL 패턴·페이징 규칙을 **코드에 하드코딩하지 말고** JSON config 또는 `app/core/crawler_config.py` 등으로 분리. 사이트 개편 시 **config만 수정**하고 재배포 없이 적용 가능하도록 설계.

- **Playwright 수집기 (필요 시)**
  - 연세대 포털·단과대 게시판 중 **정적 HTML로 수집 불가한** 페이지만 Playwright 사용. 제목, 본문, **포스터 이미지 원본 URL**(또는 images 배열) 포함.

- **데이터 정합성 (변동·복구 대비)**
  - **공지 유니크: `(college_id, external_id)`** (2단계 코드 유지). URL은 페이징/쿼리에 따라 변할 수 있어 중복 위험이 있으므로 사용하지 않음. 저장은 **upsert**로 재수집 시 중복 방지·기존 공지 갱신.
  - **본문 해시(content_hash) 기반 변경 감지**: 제목+본문(또는 raw_html) 해시를 저장. 해시가 바뀌었을 때만 4단계 AI 재추출 큐에 넣고, 그렇지 않으면 덮어쓰기·AI 호출 생략으로 비용 절감.
  - 문제 발생 시: 특정 기간/소스만 삭제 후 재수집하는 스크립트 또는 절차를 두기.

- **계층형 아키텍처 준수**
  - **DB 접근은 repositories만**. 크롤러는 `repositories`(예: college_repository, notice_repository)를 통해 College 조회·Notice upsert. `services/crawlers`에서는 비즈니스 로직(파싱·흐름 제어)만 수행.

- **Railway Playwright 워커 (인프라 필수)**
  - Nixpacks는 Chromium 등 **OS 수준 의존성**을 설치하지 않아 "Browser executable not found"로 실패함. **직접 작성한 Dockerfile** 사용. Dockerfile에 `RUN playwright install --with-deps chromium` 명시.
  - **OOM(Out of Memory) 방지**: Railway RAM 제한 때문에 Chromium 다수 실행 시 OOM Kill 위험.
    - 브라우저 실행 시 **`--no-sandbox`, `--disable-dev-shm-usage`** 옵션 반드시 추가.
    - **Celery 워커 동시성(concurrency) 1~2로 제한**. 예: `celery -A app.worker worker -l info --concurrency=1`. 브라우저가 동시에 여러 개 뜨지 않도록 함.

- **재시도·스케줄링**
  - Celery 태스크에 `autoretry_for` 등으로 재시도 설정.
  - **스케줄러: Railway Cron(또는 외부 Cron)** 으로 **POST /internal/trigger-crawl** 호출. FastAPI에 보안 키(헤더 예: X-Admin-Key 또는 쿼리) 검증 엔드포인트 구현. 해당 엔드포인트에서 Celery 크롤 태스크 enqueue. Celery Beat는 서비스 추가 비용이 들므로 사용하지 않음. Cron이 1시간마다(또는 정해진 주기로) 위 엔드포인트를 호출.

- **모니터링**
  - **Sentry를 3단계부터** 백엔드·크롤러 워커에 부착. 워커 진입점에서 Sentry 초기화. 크롤러 실패 시 빨리 추적 가능. (6단계에서 프론트 에러 추가.)

### 검증

- 로컬 또는 CI에서 Redis 연결·Celery 워커 기동 후 `crawl_college_task.delay("engineering")` 호출 시 공대 게시판 수집·DB 저장 성공 여부 확인.
- (선택) 지정 시간에 trigger-crawl 호출 → 큐 적재 → 워커 처리 end-to-end 검증.

### 마일스톤

지정 시간마다 크롤러가 최신 공지를 DB에 Raw로 저장(upsert·content_hash 반영). Playwright 워커는 Dockerfile 기반으로 Railway에서 정상 동작. POST /internal/trigger-crawl로 Cron 연동 가능.

---

## 4단계: 티어링 기반 Multimodal AI 파이프라인

### 목표

AI 비용 절감 + 파싱 에러 원천 차단. **API 429로 워커가 죽지 않도록** 속도 제한 필수.

### 할 일

- **데이터 흐름 명확화**
  - **입력**: Notice.raw_html(본문 텍스트 추출 후 AI 전달). 포스터 분석 추가 시 poster_image_url도 전달.
  - **출력**: ai_extracted_json(자격요건), deadline, event_start, event_end, event_title, hashtags. 4단계 워커는 위 컬럼만 UPDATE.

- **자격 요건·일정 스키마 (4·5·6단계 공유)**
  - Pydantic 최소 필드: **target_departments** (List[str]), **target_grades** (List[str]), **deadline** (str, ISO), **event_title** (str), **event_start** / **event_end** (str, ISO). Gemini `response_schema`에 이 형태 강제 → 파싱 에러 원천 차단. 한 곳에서 정의하고 4·5에서 import.
  - DB 저장 시 ISO 문자열 → datetime 변환. 5·6단계 **서비스 내부 달력** 및 **내보내기**에서 사용.

- **1차 키워드 필터**
  - 제목·본문에서 '점검', '단수' 등 필터 후 #일반 분류. 패턴은 config로 분리.

- **AI False Positive 지향 (프롬프트 규칙)**
  - 프롬프트에 **"판단이 애매하거나 조건이 명시되지 않은 경우, 해당 사용자에게 공지가 노출되도록(True) 설정하라"** 규칙을 명시. 놓쳐서 안 보이는 것보다, 불필요해도 한 번 더 보이는 것이 신뢰도 방어에 유리.

- **Gemini Multimodal**
  - 중요 공지 중 포스터가 있으면 이미지를 Gemini 1.5에 직접 입력. 비공개 이미지는 크롤러에서 다운로드 후 bytes/base64 전달 검토.

- **Structured Output**
  - 위 자격 요건 Pydantic 모델을 Gemini `response_schema`에 전달해 JSON 형식 강제. `clean_json_string` 파싱 제거.

- **Celery AI 태스크 속도 제한 (필수)**
  - 공지가 한 번에 많이 쌓이면 Gemini 동시 호출로 **HTTP 429** 발생, 워커 실패.
  - **rate_limit='10/m'** (분당 10회). Gemini 무료 티어 15 RPM 대비 여유 두어 429 방지. 큐에 50건이 있어도 순차·제한적으로 호출.
  - `autoretry_for`와 별도로 **rate_limit** 반드시 명시. 할당량에 따라 `6/m`, `8/m` 등 조정 가능.
  - **429 재시도 시 지수 백오프**(예: 2초→4초→8초 대기) 적용. `retry_backoff=True`, `retry_backoff_max=600` 등으로 연속 429 시 즉시 재시도하지 않도록 함.

- **재처리·롤백**
  - AI 처리 실패/잘못된 결과는 **재큐 또는 스킵 플래그**로 재처리 가능하게 설계.
  - **content_hash 변화 시에만 AI 재추출**: 3단계 크롤러에서 해시 변경 시에만 4단계 큐에 넣음. `is_manual_edited=True`인 공지는 AI로 덮어쓰지 않음.

### 마일스톤

불규칙한 포스터 공지도 AI가 JSON으로 분해해 DB에 에러 없이 반영. 대량 수집 시에도 429 없이 안정 동작.

---

## 5단계: 검색·프로필 매칭 API 완성

### 목표

정제된 DB로 **로그인한 유저**에게 맞는 공지를 골라주는 API 완성. (Auth·User는 2단계 구조, 구글 OAuth 사용.)

### 할 일

- **동적 쿼리·FTS**
  - SQLAlchemy로 검색어·필터에 따라 안전하게 쿼리 생성. PostgreSQL FTS 연동.
  - **GIN 인덱스**: `ai_extracted_json`(JSONB), 제목/본문 검색용 tsvector, hashtags 등에 Alembic 마이그레이션으로 GIN 인덱스 추가. 검색량 증가 시 성능 저하 방지.

- **맞춤 매칭**
  - 유저 프로필(전공, 학년, 군필, 학점 등)과 공지 자격 요건(JSON) 비교 로직을 `services/`에 구현. 4단계와 공유한 자격 요건 스키마 사용.

- **API·문서**
  - 공개 API는 **`/v1/` prefix**. 스키마 변경 시 기존 필드 삭제·이름 변경은 하지 않고, 추가만 하거나 새 버전(/v2/)으로 올리기.
  - **`GET /v1/users/me`**: JWT로 식별된 로그인 유저 프로필 조회 (5·6단계 프로필 매칭·설정 UI 필수).
  - 정렬·필터·페이지네이션 엔드포인트 완성, Swagger 문서화. 예시는 README/Postman에 정리.

- **일정·달력 API (핵심 기능)**
  - **user_calendar_events**: 2단계 스키마 유지 + **UniqueConstraint(user_id, notice_id)** 추가 (한 공지를 내 달력에 중복 추가 방지).
  - **추출 일정 목록 API**: **GET /v1/calendar/events?year=2026&month=3** (월별 쿼리, 달력 UI 그리기 편함). 응답: (1) 유저 프로필에 매칭된 공지 중 deadline 또는 event_start가 있는 객체 배열, (2) user_calendar_events 객체 배열. 프론트에서 두 배열 병합하여 그리기.
  - **서비스 내부 달력**: 위 API로 "내 일정" 기간별 조회. "내가 추가한 일정"과 "매칭 공지에서 추출된 일정"을 함께 반환.
  - **내보내기**
    - **.ics 다운로드**: 선택한 일정 또는 기간 내 일정을 iCalendar(.ics) 파일로 생성해 다운로드. Google Calendar, Apple Calendar, Outlook 등에서 임포트 가능.
    - **Google Calendar 연동(선택)**: 구글 OAuth에 캘린더 쓰기 scope 추가 후, "Google 캘린더에 추가" 버튼으로 선택 일정을 사용자 구글 캘린더에 직접 삽입.

### 마일스톤

Swagger UI에서 임의 프로필 입력 시 지원 가능한 공지만 필터링되어 응답. **일정 목록 API**로 기간별 추출 일정 조회 가능. (실서비스는 JWT로 식별된 유저 프로필 사용.)

---

## 6단계: Next.js 프론트 연동 및 최종 런칭

### 목표

백엔드 API를 UI와 연결해 실제 사용자가 접속 가능한 환경을 연다.

### 할 일

- **Next.js**
  - 프론트 세팅, Vercel 연동.

- **반응형·모바일 우선**
  - 레이아웃·폰트·터치 영역이 작은 화면·세로 모드에서도 읽기·탭하기 쉽게. 모바일 기준으로 먼저 디자인 후 데스크톱으로 확장. 버튼·링크는 최소 44×44px 수준의 터치 친화적 UI. Safe Area(노치·상태바) 대응.

- **API 연동·UI**
  - 매칭 API 호출. **구글 로그인** 후 프로필에 맞는 공지를 피드로 표시. 목록·이미지 로딩 전략(페이지네이션·무한 스크롤, 이미지 lazy loading·WebP 최적화). 스켈레톤 UI로 첫 로드 체감 대기 완화. 네트워크 에러 시 안내·재시도 UI.

- **서비스 내부 달력 (핵심 기능)**
  - **달력 표시 방식 (6단계 진입 전 확정)**
    - **확정**: **한 화면 통합 + 시각적 구분 + 토글(스위치) 필터**. 탭으로 화면을 나누는 방식은 사용하지 않음(일정 충돌 확인이 달력 본질이므로, 탭으로 나누면 사용자가 두 탭을 오가며 머릿속으로 합쳐야 해 UX상 불리함).
    - **시각적 구분**
      - **내가 추가한 일정 (우선)**: 진한 색(예: 연세 블루), 꽉 찬 점(Solid dot) 또는 텍스트 배경색. 눈에 먼저 띄도록.
      - **매칭/추출 일정 (제안)**: 연한 색(파스텔·회색), 테두리만 있는 빈 점(Hollow dot). AI가 넌지시 제안하는 느낌.
    - **토글/필터**: 달력 상단 우측에 칩(Chip) 또는 스위치: **[전체 보기]** / **[내 저장 일정만]**. 평소에는 전체로 새 공지 탐색, 스케줄 관리 시 "내 저장 일정만"으로 정리해 보기.
  - **내부 달력 UI**: 월/주 뷰 달력 화면. 5단계 일정 API(`/v1/calendar/events`)로 가져온 추출 일정(신청 마감, 행사일 등)을 표시. 공지 제목·링크·일정 타입(마감/행사) 구분 표시. 모바일(세로) 레이아웃·스와이프·터치 제스처 고려. 뒤로 가기와 브라우저 백버튼 자연스럽게 연동. 표시 방식은 위 "달력 표시 방식" 확정 사항 따름.
  - **내 달력에 추가**: 유저가 공지 상세에서 "내 달력에 추가" 시 서비스 내부 저장(user_calendar_events). 내부 달력에서는 위 확정된 한 화면 통합 + 시각적 구분 + 토글 필터로 표시.
  - **내보내기 UI**
    - **.ics 다운로드**: "내보내기" 버튼으로 선택 일정 또는 기간 내 일정을 .ics 파일 다운로드.
    - **Google 캘린더에 추가**(5단계에서 API 구현 시): 버튼 클릭 시 사용자 구글 캘린더에 해당 일정 추가.

- **프로필·폼 모바일 대응**
  - 프로필 설정(전공, 학년 등) 폼: 가상 키보드·뷰포트 대응, `inputmode` 활용, 스텝/섹션 분리로 세로 스크롤 부담 완화.

- **스크롤 복원**
  - 목록 → 상세 → 뒤로 가기 시 스크롤 위치 복원. Next.js scrollRestoration 또는 sessionStorage 검토.

- **모니터링**
  - Sentry는 3단계에서 이미 백엔드·워커에 부착됨. 6단계에서 **프론트 에러** 추가. 에러에 `task_id`, `notice_id` 등 컨텍스트 포함.

### 마일스톤

Vercel 배포 사이트에서 프로필 설정 후 자신에게 맞는 최신 공지를 에러 없이 확인 가능. **서비스 내부 달력**에서 추출된 일정(마감·행사) 확인 및 "내 달력에 추가" 가능. **.ics 내보내기**로 외부 달력에 저장 가능 → 베타 런칭 완료.

---

## 추가 검토 아이디어

- 새로 떠오른 기능·변경은 **여기에만** 적고, 현재 단계가 끝날 때까지 로드맵 본문은 유지.
- 로드맵 본문 수정 시: **날짜**, **수정 내용**, **이유**를 한 줄씩 기록.
- 단계별 목표 기간(예: N주)은 로드맵 상단 [단계별 목표 기간](#단계별-목표-기간) 표에 넣고, 지연 시 WORK_LOG에 사유 기록하면 일정 변동 추적에 유리함.
- 각 아이디어는 **고려 시점**(몇 단계 이전 / 해당 단계 / 이후)을 문구 또는 괄호로 명시한다.
- 단계가 끝나면 **해당 단계·이전 단계**에 해당하는 검토 아이디어에 대해 사용자에게 물어본다(규칙: `.cursor/rules/roadmap-and-worklog.mdc` 참고).

### 2026-02-17 반영

- **고려 시점: 1단계** — **CI/CD 파이프라인 구축 완료**: 1단계 "검증(변동 대비)" 반영. GitHub Actions로 push/PR 시 Ruff(린트) → Mypy(타입) → Pytest(테스트) 자동 실행. `tests/`, `pyproject.toml`, `.github/workflows/ci.yml` 추가. (이미 반영 완료.)
- **고려 시점: 3단계 이후 ~ 6단계 직전** — **API Rate Limit (클라이언트 방어)**: Celery↔Gemini rate_limit은 있으나, FastAPI 엔드포인트를 외부가 무작위 호출(DDoS·악의적 크롤링)하는 방어는 미비. Redis가 붙는 3단계 이후 또는 6단계(프론트 공개) 직전에 **slowapi** 등으로 백엔드 API 자체에 Rate Limit 적용 검토.
- **고려 시점: 3단계 이후, 6단계 이전** — **토큰 무효화·로그아웃**: 3단계 Redis 도입 후, 6단계(프론트 공개) 전에 로그아웃 시 Refresh 토큰 블랙리스트 또는 User.token_version 기반 무효화 검토.
- **고려 시점: 5단계** — **Repository → DTO 반환 (5단계 또는 관계 복잡해질 때)**: user_repository 등이 ORM 대신 Pydantic(UserResponse 등) 반환하도록 변경. 5단계 calendar API·user_calendar_events 복합 관계 시 LazyLoading/Detached 위험 감소 목적.
- **고려 시점: 3단계 이후** — **테스트 확장 (3단계 CI PostgreSQL 이후)**: GitHub Actions에 PostgreSQL 서비스 추가, `DATABASE_URL` 설정. auth 통합 테스트(httpx mock + 실제 DB), Notice/크롤러 관련 통합 테스트 추가.
- **고려 시점: 6단계 이후** — **Observability (6단계 베타 또는 트래픽 증가 시)**: Correlation ID 미들웨어(`X-Request-ID`), structlog 등 구조화 로깅, Sentry에 `request_id` 태깅.
- **고려 시점: 단계 완료 시마다** — **문서 정합성 점검**: 확정 사항 변경 시 ROADMAP·CAUTIONS·DEPLOYMENT 동시 갱신. 본문 "정해 두기" 표현은 확정 사항 표와 맞는지 확인.

### 2026-02-17 모바일 사용자 고려

- **고려 시점: 6단계 이후** — **PWA(홈 화면 추가)**: "홈 화면에 추가"로 앱처럼 아이콘으로 사용. 모바일 사용자 재방문 유리.
- **고려 시점: 6단계 이후** — **웹 푸시(새 공지 등)**: "새 공지 올라왔어요" 등 알림. 모바일에서 재방문률·활용도 상승. 6단계 이후 검토.
- **고려 시점: 6단계** — **메타·OG 태그**: 링크 공유 시 썸네일·제목·설명 노출. SNS·메신저 공유 시 모바일 경험 개선.
- **고려 시점: 6단계** — **Web Share API**: 공지 상세에서 모바일 네이티브 "공유하기" 연동. 카카오톡·메신저 공유 편의.
- **고려 시점: 6단계** — **데이터 절약 모드**: `navigator.connection.saveData` 또는 사용자 설정으로 이미지 저화질·lazy loading 강화.
- **고려 시점: 6단계** — **접근성(WCAG)**: 스크린 리더(aria-label, 시맨틱 HTML), 색상 대비, 폰트 크기 조절 반영. `user-scalable=no` 금지.
- **고려 시점: 6단계** — **OAuth 모바일 플로우 검증**: 6단계 구글 로그인 연동 시 모바일 브라우저·WebView에서 OAuth 리다이렉트·토큰 전달 정상 동작 확인.

### 2026-02-17 단계별 결정 사항 반영 (로드맵 본문 수정)

- **3단계**: 공지 유니크 `(college_id, external_id)` 확정. 스케줄러를 Railway Cron + POST /internal/trigger-crawl(보안키 검증)로 명시. Celery Beat 비사용 이유(비용) 명시.
- **4단계**: 입력(raw_html 본문 추출·poster_image_url)/출력(ai_extracted_json, deadline, event_*, hashtags) 명시. 자격요건 Pydantic 최소 필드(target_departments, target_grades, deadline, event_title, event_start/end) 및 rate_limit='10/m' 명시.
- **5단계**: user_calendar_events에 UniqueConstraint(user_id, notice_id). 일정 API GET /v1/calendar/events?year=&month= 및 응답(매칭 공지 일정 배열 + user_calendar_events 배열) 스펙 명시.
- **이유**: 사용자와 합의한 선택을 로드맵·코드·배포 문서에 반영해 이후 단계 구현 시 일관성 유지.

### 2026-02-18 지금 상태·3단계 상세 반영 (로드맵 본문 수정)

- **지금 상태**: 현재 단계를 "3단계 진행 중"으로 변경. 이번 목표에 Celery·Redis 완료, 크롤러 Repository 분리·upsert·content_hash, trigger-crawl API, Dockerfile 워커, Sentry 워커 부착 명시. "3단계 구현 현황" 표 링크 추가.
- **3단계**: "3단계 구현 현황 (진행 중)" 표 추가 — 할 일 항목별 구현 여부(✅/❌/⚠️)·파일·규칙 준수. 할 일에 계층형 아키텍처(DB는 repositories만)·upsert·content_hash·trigger-crawl 상세 보강. 검증·마일스톤 문구 보강. Notice 스키마 정합성(dates/eligibility vs deadline/event_*) 안내 및 4단계 진입 전 결정 필요 명시.
- **미리 결정 필요**: 4단계 "Notice 일정 스키마 정합성" 행 추가.
- **이유**: 3단계 진행 중 어디까지 구현되었는지·규칙 대비 누락을 한눈에 보이게 하고, 남은 작업·마일스톤을 명확히 하기 위함.
