# DICEE 단계별 실행 상세 (Phase Playbooks)

이 문서는 [ROADMAP](ROADMAP.md)의 **전략·마일스톤·기둥·지표**에 대응하는 **단계별 할 일·확정 사항·예상 문제·추가 검토 아이디어·기술 부채 반영 계획**을 담는다.  
결정 근거는 [ADR](decisions/), 실제 수정 기록은 [WORK_LOG](WORK_LOG.md).

---

## 목차

- [확정 사항 (코드·문서 기준)](#확정-사항-코드문서-기준)
- [미리 결정 필요 (진입 전)](#미리-결정-필요-진입-전)
- [진행 시 예상 문제·대비](#진행-시-예상-문제대비-블로커병목)
- [단계별 목표 기간](#단계별-목표-기간)
- [1단계 ~ 6단계 상세](#1단계--6단계-상세)
- [추가 검토 아이디어](#추가-검토-아이디어)
- [기술 부채·품질 개선 계획](#기술-부채품질-개선-계획-테크-리드-리뷰-반영)

---

## 확정 사항 (코드·문서 기준)

이미 코드·문서에서 확정된 사항. "2단계에서 결정" 등 본문 표현이 있어도 여기 한곳만 보면 된다.


| 구분                | 확정 내용                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **데이터 구조**        | Raw vs 정제: **같은 테이블(Notice)에 단계별 컬럼**(raw_html → ai_extracted_json). 별도 Raw 테이블 없음.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **일정 저장**         | [ADR 001 — Notice 일정 스키마](decisions/001-notice-schedule-schema.md)에 따라 구현. **결정 시점: 3단계 DB 스키마 확정 전.** 현재 DB(005): dates·eligibility(JSONB). 공지-일정 1:N 테이블 없음.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| **OAuth 토큰**      | **응답 body JSON**으로 Access/Refresh JWT 반환. Set-Cookie 미사용. 프론트는 Authorization 헤더. (DEPLOYMENT·코드 일치)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **3단계**           | 공지 유니크 `(college_id, external_id)`. 스케줄러: Railway Cron + POST /internal/trigger-crawl. Celery Beat 미사용(비용). **크롤러 소스**: [SeaLion-hub/crawler](https://github.com/SeaLion-hub/crawler) 레포. 이식 시 레포 readme 주의사항 준수. **아래 3단계 확정(구현 원칙)** 적용.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **3단계 확정(구현 원칙)** | **(1) Celery payload**: 크롤러는 수집 데이터를 **DB에만 저장**. 4단계 AI 큐에는 **notice_id(또는 id 목록)만** 전달. raw_html·이미지 바이트를 Redis 인자/반환값으로 넣지 않음. AI 워커는 notice_id로 DB에서 조회. **(2) content_hash**: BeautifulSoup 파싱 후 **조회수·날짜·하단 배너 등 본문 외 요소 제거**, **제목 + 순수 본문 텍스트(get_text())**만으로 sha256 생성. raw_html 전체 해시 금지. **(3) Upsert**: PostgreSQL `insert(Notice).on_conflict_do_update(index_elements=['college_id','external_id'], set_={...})` 사용. NoticeRepository에 캡슐화. **(4) Celery 워커 DB**: 워커(크롤러·AI 태스크)는 **동기 DB(psycopg2)** 전용. asyncpg는 FastAPI 웹만. **(5) Redis broker**: redis:// 및 **rediss://(TLS)** 모두 지원. Railway Redis TLS 시 ssl_cert_reqs 등 적용. **(6) Polite crawling**: 요청/페이지 간 **1초 딜레이**. 여러 단과대 **순차** 실행(concurrency=1 또는 trigger에서 college별 순차 enqueue). **(7) 크롤 주기**: **6시간마다** (IP 차단 리스크 완화·비용·최신성 균형. 학교 전산처 비정상 트래픽 감지 시 Railway IP 차단 가능성 있으므로 요청 빈도 완화. 완전 보장은 없음.) **(8) external_id**: 레포 모듈별 반환(no, url)에 맞춰 **게시글 번호(no) 우선, 없으면 URL path에서 추출**. 모듈별 config 문서화. |
| **4단계**           | 입출력·자격요건 Pydantic 필드·rate_limit='10/m'. **3→4 전달**: notice_id만 큐에 넣고, AI 워커는 DB에서 raw_html 등 조회. (위 3단계 확정 payload 원칙.)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **5단계**           | GET /v1/calendar/events?year=&month=, 응답 두 배열. user_calendar_events UniqueConstraint(user_id, notice_id).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **6단계 달력 UX**     | **한 화면 통합 + 시각적 구분 + 토글 필터**. 탭 분리 비권장(일정 충돌 확인이 달력 본질).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |


---

## 미리 결정 필요 (진입 전)

각 단계 진입 전 또는 해당 단계 설계 시 결정해야 할 사항. 상세 비교·결정 근거는 [ADR 001](decisions/001-notice-schedule-schema.md) 등 참고.

### 일정 스키마 (A vs B) — 단일 참조

**결과만 로드맵에 기입.** (예: "3단계: 일정 스키마 **A(DateTime 컬럼형)** 적용" 또는 "**B(dates JSONB 유지)** 적용")  
**결정 시점**: 3단계 DB 스키마 확정 전.


| 단계      | 항목                                                    | 결정 시점               | 설명                                                                                                                             |
| ------- | ----------------------------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| 3단계     | College 목록·external_id                                | 3단계 시작 전            | 수집할 단과대/게시판 목록, College.external_id 정의. College별 크롤러 모듈·목록 URL 매핑을 config·시드에 문서화. (확정: external_id는 게시글 번호 우선, 없으면 URL path.) |
| 3단계     | ~~Notice.external_id~~ / ~~크롤 주기~~ / ~~content_hash~~ | —                   | **결정 완료.** 확정 사항 "3단계 확정(구현 원칙)" 참고.                                                                                           |
| **3단계** | **Notice 일정 스키마 (A vs B)**                            | **3단계 DB 스키마 확정 전** | [ADR 001](decisions/001-notice-schedule-schema.md) 참고. 결정 후 3단계 마이그레이션·크롤러 매핑·4·5·6 할 일 일괄 적용.                                 |
| 4단계     | User↔AI 매칭 규칙                                         | 4단계 스키마 설계 시        | User.profile_json(major, grade 등)와 ai_extracted_json(target_departments, target_grades)의 매칭 로직. "포함 여부" vs "정확 일치".            |
| 4단계     | 학과·학년 값 형식                                            | 4단계 스키마 설계 시        | target_departments, target_grades 값 범위·형식 통일. User 프로필 값과 비교 가능하도록.                                                            |
| 5단계     | 목록 API 페이지네이션                                         | 5단계 API 설계 시        | cursor vs offset, 기본 page_size. 6단계 무한 스크롤 설계에 영향.                                                                             |
| 5단계     | 일정 API 필터 범위                                          | 5단계 API 설계 시        | year, month 외 day 또는 from/to 필요 여부. 6단계 주간 뷰 등에 영향.                                                                            |


---

## 진행 시 예상 문제·대비 (블로커·병목)

구현 단계에서 **반드시 고려**할 이슈와 대비. [ROADMAP](ROADMAP.md) Technical Pillars와 [CAUTIONS](CAUTIONS.md)와 함께 참고.


| 구분                      | 예상 문제                                                                                                | 대비                                                                                                                 |
| ----------------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| **Celery + 비동기 DB**     | Celery는 동기, FastAPI·DB는 비동기. 태스크 안에서 asyncio.run()으로 DB 접근 시 커넥션 반환 불완전 → "Too many connections" 위험. | Celery 워커 전용 **동기 DB 세션(psycopg2)** 별도 구성. 크롤러·AI 태스크에서 위 방식 채택.                                                   |
| **429·지수 백오프**          | 대량 수집 시 AI 큐에 한꺼번에 쌓이면 Gemini RPM 초과 → 429 → 워커 실패.                                                  | **rate_limit='10/m'** 필수. **지수 백오프** 재시도(Celery retry_backoff=True 등).                                             |
| **Playwright OOM**      | Chromium 메모리 사용량 큼. Railway 등 RAM 제한 환경에서 동시 실행 시 OOM Kill.                                          | Playwright는 **정적 HTML 수집 불가 시에만** 사용. `--no-sandbox`, `--disable-dev-shm-usage` 필수. Celery **concurrency 1~2** 강제. |
| **AI False Positive**   | "애매하면 노출(True)"로 누락은 막지만, 무관한 공지 노출로 피로도 증가.                                                         | 6단계 UI에 "나와 관련 없는 공지" 버튼 → 피드백 저장·AI 매칭 고도화용 데이터 수집.                                                               |
| **Celery payload 크기**   | raw_html·이미지를 태스크 인자/반환으로 넘기면 Redis 메모리·병목.                                                          | **데이터는 DB에만 저장.** 3→4 전달은 **notice_id만**. AI 워커는 DB에서 조회.                                                          |
| **Redis TLS**           | Railway Redis는 rediss://(TLS). redis://만 가정하면 연결 실패.                                                 | broker_url에서 **redis://·rediss://** 모두 대응. TLS 시 ssl_cert_reqs 등 적용.                                               |
| **방화벽·IP 차단**           | 크롤러가 빠르게·동시에 요청하면 연세대 방화벽에서 DDoS로 간주·IP 차단 가능.                                                       | **Polite crawling**: 요청/페이지 간 **1초 딜레이**. 단과대 **순차** 실행. **크롤 주기 6시간**.                                            |
| **순간 동시 요청(Burst)**     | 6시간 정각에 여러 단과대·수십 페이지를 1~2초 안에 동시 요청하면 WAF가 IP 밴 가능.                                                 | 요청 간 **최소 1~2초** 지연. 페이지네이션 시에도 동일 지연.                                                                             |
| **Thundering Herd**     | 모든 단과대 크롤러가 같은 시각에 출발하면 서버에 한꺼번에 요청 집중.                                                              | **크롤 시작 시간 분산**: 단과대별 **5분 간격** countdown. `apply_async(args=[code], countdown=i*300)`.                            |
| **데이터센터 IP·User-Agent** | Railway/AWS IP는 데이터센터 IP. 대학 WAF가 차단할 수 있음. 기본 UA는 차단 확률 높음.                                         | **실제 Chrome 브라우저 User-Agent** 사용. crawler_config.CRAWLER_HEADERS에 Chrome UA·Accept·Accept-Language 정의.             |
| **크롤링 의존성(단일 장애점)**     | 학교 전산처가 지속 크롤링을 비정상 트래픽으로 간주해 Railway IP를 예고 없이 차단할 수 있음.                                            | 크롤 주기 **6시간**. IP 차단 시 **수동 trigger-crawl**·모니터링(Sentry·로그)으로 조기 감지.                                               |
| **IP 차단(Timeout·403)**  | Railway 등 데이터센터 IP는 대학 WAF에서 차단·패턴 감지 시 밴되기 쉬움.                                                      | Timeout·403 다발 시 IP 차단 의심. **프록시 로테이션**(ScraperAPI, ZenRows 등) 검토.                                                 |
| **크롤러 HTTP·예외**         | timeout 미지정 시 워커 Hang. except Exception으로 에러 삼키면 재시도 불가·원인 파악 불가.                                    | 모든 HTTP 요청에 **timeout**(예: 10초) 필수. **RequestException**은 raise. 파싱 오류는 logging.exception() 후 raise 또는 스킵.         |
| **일정 스키마·5단계 성능**       | Notice가 dates(JSONB)만 있으면 날짜 범위 쿼리 복잡·달력 API 병목.                                                     | [ADR 001](decisions/001-notice-schedule-schema.md) 참고. (A) 권장.                                                     |
| **Push 알림 부재**          | 매칭 결과를 유저가 앱을 열 때만 보면 리텐션 저하.                                                                        | 4단계에서 **매칭 시 알림 큐 enqueue**. 6단계에서 FCM·APNs·웹 푸시 연동.                                                               |
| **깨진 링크(Dead Link)**    | 공지 삭제·숨김 시 원문 링크 404 → 서비스 신뢰 하락.                                                                    | raw_html로 앱 내 본문 표시(원문 실패 시 대체). 주기적 **링크 유효성 체크** 후 [마감됨]/[링크 만료] 라벨.                                             |
| **Celery 침묵 실패·큐 정체**   | 셀렉터 변경 등으로 크롤/AI 태스크가 계속 실패하면 무한 재시도로 큐 막힘.                                                          | **max_retries** 후 **Dead Letter Queue**로 보내 수동 검토. 무한 재시도 금지.                                                      |
| **Redis 영속성**           | Redis를 Celery broker·알림 큐로 사용 시 서버 재시작/장애 시 큐 유실.                                                    | **Railway Redis 플랜 확인** 필수. **AOF 또는 RDB 백업** 활성화. DEPLOYMENT에 Redis 영속성 설정 안내 포함.                                 |


---

## 단계별 목표 기간


| 단계  | 목표 기간(주) | 비고                |
| --- | -------- | ----------------- |
| 1단계 | 완료       | —                 |
| 2단계 | 완료       | —                 |
| 3단계 | 1주~1.5주  | 지연 시 WORK_LOG에 사유 |
| 4단계 | 2~3주     | —                 |
| 5단계 | 1~2주     | —                 |
| 6단계 | 3주       | —                 |


---

## 1단계 ~ 6단계 상세

### 1단계: 비동기 백엔드 뼈대 구축 및 Railway 개통

**목표**: 단일 파일 의존 구조를 버리고, 계층형 아키텍처를 세운 뒤 Railway에 빈 서버를 배포한다.

**할 일 요약**: 진입점 `app.main:app`, `app/` 내 api/, core/, services/, repositories/, models/, schemas/. 환경변수·.env.example 키 이름만. 에러·로깅 정책. Sentry 1단계에서 DSN 설정. Railway CI/CD, Start Command: uvicorn app.main:app --host 0.0.0.0 --port $PORT.

**마일스톤**: Railway 도메인으로 `GET /health` → 200 + `{"status":"ok"}`.

---

### 2단계: 비동기 DB(PostgreSQL) 및 ORM·Auth 설계

**목표**: ORM으로 안전하게 데이터를 다루고, **유저 인증/인가 설계를 확정**한다.

**할 일 요약**: 로컬·Railway DATABASE_URL. PostgreSQL + asyncpg. SQLAlchemy 2.0으로 Notice, College, User 정의. Raw vs 정제: 같은 테이블(Notice)에 단계별 컬럼. 일정 저장은 [ADR 001](decisions/001-notice-schedule-schema.md)에 따라(결정 시점: 3단계 DB 스키마 확정 전). content_hash, is_manual_edited 미리 설계. **Auth**: 구글 로그인(OAuth) 먼저, JWT 발급. 구글 ID 토큰 서명 검증(verify_signature=False 금지). User: provider, provider_user_id, 프로필 필드. OAuth 핸드쉐이크: 응답 body JSON으로 Access/Refresh JWT, 프론트는 Authorization 헤더. 프론트에서 구글 OAuth 후 Authorization Code를 백엔드 `/v1/auth/google`로 전달 → 백엔드가 구글 검증 후 자체 JWT 발급. Alembic 마이그레이션 세팅.

**마일스톤**: DB 클라이언트로 테이블 확인 가능. Auth 방식(구글 OAuth + JWT)과 User 스키마 문서화 완료.

---

### 3단계: 연세대 크롤러(레포 이식) 및 작업 큐 연동

**목표**: 연세대 공지 수집을 [SeaLion-hub/crawler](https://github.com/SeaLion-hub/crawler) 레포 기반 자체 엔진으로 전환하고, Celery에서 공지를 수집·DB 저장하는 파이프라인을 완성한다.

**할 일 요약**:  

- 크롤러 소스: SeaLion-hub/crawler. 이식 시 실제 공지 목록 URL 인자로 주입, scrape_detail 등 추출 로직 수정 금지, 반환 본문은 HTML.  
- College↔크롤러 모듈·URL 매핑을 config 또는 시드에 정의.  
- Celery 앱 진입점(예: app/worker.py), broker=Redis. 크롤링 전용 워커.  
- 데이터: requests+BeautifulSoup(레포 기준). httpx 대체 가능하면 사용. HTTP timeout 필수, RequestException raise, User-Agent는 Chrome UA. Playwright는 정적 HTML 불가 시에만.  
- 공지 유니크 (college_id, external_id). Upsert on_conflict_do_update, NoticeRepository 캡슐화. content_hash: 제목+순수 본문 텍스트만 sha256. 해시 변경·신규 시에만 4단계 AI 큐 enqueue.  
- Tombstone(선택): 이번 사이클 목록에 없는 external_id는 is_deleted=True 등으로 갱신.  
- Payload: raw_html·이미지는 Redis 거치지 않음. 4단계에는 notice_id만 전달. Broker: redis://·rediss:// 지원.  
- Polite crawling: 1초 딜레이, 단과대별 5분 stagger.  
- Celery 워커 DB: 동기 psycopg2 전용.  
- Railway 워커: Playwright 필요 시에만 Dockerfile, OOM 방지 옵션·concurrency 1~2.  
- 재시도·스케줄링: autoretry_for, max_retries 후 DLQ. Railway Cron으로 POST /internal/trigger-crawl, 크롤 주기 6시간.  
- 모니터링: Sentry 워커 부착.

**3단계 → 4단계 전 검크리스트**: content_hash 중복 없음(약 100건 적재 후 확인). 날짜 형식 정상.

**마일스톤**: 지정 시간마다 크롤러가 최신 공지를 DB에 upsert·content_hash 적용. POST /internal/trigger-crawl로 Cron 연동 가능. 검크리스트 통과 후 4단계 진입.

---

### 4단계: 티어링 기반 Multimodal AI 파이프라인

**목표**: AI 비용 절감 + 파싱 에러 원천 차단. **API 429로 워커가 죽지 않도록** 속도 제한 필수.

**할 일 요약**: 3→4 전달은 notice_id만. AI 입력 전 raw_html 정제(Clean HTML)로 Gemini 토큰 초과·400 방지. 입출력: ai_extracted_json(자격요건), hashtags, 일정 데이터(ADR 001). 자격 요건·일정 스키마 4·5·6 공유, Pydantic으로 Gemini response_schema 강제. AI False Positive 지향(애매하면 True). Gemini Multimodal(포스터 이미지). Structured Output만 사용. **Celery AI 태스크 rate_limit='10/m'**, 지수 백오프 재시도, max_retries 후 DLQ. content_hash 변화 시에만 AI 재추출. is_manual_edited=True인 공지는 AI로 덮어쓰지 않음. LLMOps: 프롬프트 버저닝·A/B·Fallback. Push 알림 파이프라인: 매칭 결과 → 알림 큐 enqueue(실제 발송은 5·6단계).

**마일스톤**: 불규칙한 포스터 공지도 AI가 JSON으로 분해해 DB에 에러 없이 저장. 429 없이 안정 동작. 매칭 시 알림 큐 이벤트 전달 설계 반영.

---

### 5단계: 검색·프로필 매칭 API 완성

**목표**: 정제된 DB로 **로그인한 유저**에게 맞는 공지를 골라주는 API 완성.

**할 일 요약**: PostgreSQL FTS(tsvector), GIN 인덱스(ai_extracted_json, tsvector, hashtags). 수동 검색(키워드) 수요 대비. 유저 프로필과 공지 자격 요건(JSON) 비교 로직 services에 구현. API /v1/ prefix. GET /v1/users/me. 정렬·필터·페이지네이션, Swagger 문서화. user_calendar_events UniqueConstraint(user_id, notice_id). GET /v1/calendar/events?year=&month=, 응답: 매칭 공지 중 일정 배열 + user_calendar_events 배열. .ics 다운로드. Google Calendar 연동(선택).

**마일스톤**: Swagger에서 임의 프로필 입력 시 지원 가능한 공지만 필터링 응답. 일정 목록 API로 기간별 추출 일정 조회 가능.

---

### 6단계: Next.js 프론트 연동 및 최종 런칭

**목표**: 백엔드 API를 UI와 연결해 실제 사용자가 접속 가능한 환경을 연다.

**할 일 요약**: Next.js 세팅, Vercel 연동. 반응형·모바일 우선(레이아웃·폰트·터치 44×44px, Safe Area). 이용약관·개인정보처리방침 필수. 달력 UX: 한 화면 통합 + 시각적 구분 + 토글 필터(탭 분리 비권장). 깨진 링크: raw_html로 앱 내 본문 표시, 링크 유효성 체크 후 [마감됨]/[링크 만료] 라벨. CORS·Credentials 정책(구글 OAuth·백엔드 JWT 발급 흐름에 맞춤). Sentry 프론트 에러. "나와 관련 없는 공지" 버튼(피드백 수집).

**마일스톤**: 실제 사용자가 접속 가능. 모바일·데스크톱에서 공지 조회·달력·맞춤 피드 이용 가능.

---

## 추가 검토 아이디어

- 새로 떠오른 기능·변경은 **여기에만** 적고, 현재 마일스톤이 끝날 때까지 본문은 유지.
- 각 아이디어는 **고려 시점** 명시. 마일스톤 완료 시 해당·이전 시점 검토 아이디어에 대해 사용자에게 확인 요청(규칙: `.cursor/rules/roadmap-and-worklog.mdc`).

**3단계·크롤러 관련**

- **3단계 마무리 또는 4단계 전** — 배치 조회: get_by_college_external_sync 호출 배치화.
- **3단계 마무리** — 워커 기동 시 init_sync_db() 호출. trigger-crawl delay() 실패 시 503+로그.
- **크롤러 정리 시** — 공통 HTTP 래퍼(timeout·RequestException 정책).
- **3단계 마무리 또는 4단계** — Redis 분산 락(crawl_lock:{college_code}). 타임아웃 짧게(예: 3~5분), timeout=3600 금지.

**시니어·QA·인프라**

- **4단계 이후 또는 6단계 이후** — 비동기 큐 전환(Celery → ARQ 등).
- **3단계 마무리 또는 크롤러 정리 시** — 크롤러 레지스트리·Base 클래스.
- **4단계 또는 크롤러 정리 시** — httpx·병렬 크롤링·Bulk Upsert(트레이드오프: Polite crawling).
- **3단계 마무리** — CI PostgreSQL 서비스.
- **4단계 또는 배포 안정화 시** — Health 확장·"마지막 성공 크롤" 모니터링.

**기술·운영**

- **5·6단계 이후 또는 데이터 축적 후** — 데이터 수명 주기·파티셔닝·아카이빙.
- **1단계** — CI/CD: Ruff → Mypy → Pytest.
- **3단계 이후 ~ 6단계 직전** — API Rate Limit(slowapi 등).
- **5단계** — Repository → DTO 반환 검토.
- **6단계 이후** — Observability(Correlation ID, structlog, Sentry request_id).
- **6단계 이후** — AI False Positive 고도화(is_manual_edited·어드민).

**모바일·UX**

- **6단계 이후** — PWA, 웹 푸시.
- **6단계** — 메타·OG 태그, Web Share API, 접근성(WCAG), OAuth 모바일 플로우 검증.

---

## 기술 부채·품질 개선 계획

테크 리드·시니어 풀스택 리뷰에서 지적된 항목을 계획표로 정리. **우선순위**: P0(즉시) → P1 → P2 → P3.  
상세 표·코드 반영 내역은 이전 ROADMAP 이력 또는 WORK_LOG 참고. 요약만 아래에 둠.

- **P0**: 비동기 크롤러 전환(A1), DRY 플로우 공통화(A2), JWT iss/aud(S1), 구글 응답 Pydantic 검증(S5·R1). **P0 머지 전에는 새 기능 코드 금지.**
- **P1**: OOM 방어(E1) 청크+expunge_all+참조 해제, Sentry except Exception 제거(S3), compare_digest(S4), trigger-crawl async def(O2). 3단계 완료 전 Hotfix(S3) 필수.
- **P2**: 인프라 원칙(S2), redirect_uri 설정화(E2), 예외 정책 문서화(R2).
- **P3**: DB 풀 설정화(E3), health status(R3), 노이즈 파라미터(O1).

**시니어 리뷰**: SRP(crawl_service 유틸 분리), Sentry 데코레이터 분리(CQ1), 구글 토큰 asyncio.to_thread(CQ2), make_url(PERF1), 트랜잭션·expunge 명시(PERF2), defer 목록 조회(PERF3), 구조화된 에러 응답(SEC1), _build_bulk_upsert_stmt(DRY1), 인덱싱(IDX1~3).

**결론**: 문서 계획이 코드가 되기 전까지는 의미 없다. P0 브랜치부터 작업·PR 시 코드 라인 단위 리뷰.