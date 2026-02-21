# DICEE 개발 로드맵

## 목차

- [지금 상태](#지금-상태)
- [확정 사항 (코드·문서 기준)](#확정-사항-코드문서-기준)
- [미리 결정 필요 (진입 전)](#미리-결정-필요-진입-전)
  - [일정 스키마 (A vs B) — 단일 참조](#일정-스키마-a-vs-b-단일-참조)
- [단계별 목표 기간](#단계별-목표-기간)
- [1단계: 비동기 백엔드 뼈대 구축 및 Railway 개통](#1단계-비동기-백엔드-뼈대-구축-및-railway-개통)
- [2단계: 비동기 DB(PostgreSQL) 및 ORM·Auth 설계](#2단계-비동기-dbpostgresql-및-ormauth-설계)
- [3단계: 연세대 크롤러(레포 이식) 및 작업 큐 연동](#3단계-연세대-크롤러레포-이식-및-작업-큐-연동)
  - [3단계 구현 현황](#3단계-구현-현황-진행-중)
  - [3단계 진행 과정 (코드 기준)](#3단계-진행-과정-코드-기준)
- [4단계: 티어링 기반 Multimodal AI 파이프라인](#4단계-티어링-기반-multimodal-ai-파이프라인)
- [5단계: 검색·프로필 매칭 API 완성](#5단계-검색프로필-매칭-api-완성)
- [6단계: Next.js 프론트 연동 및 최종 런칭](#6단계-nextjs-프론트-연동-및-최종-런칭)
- [추가 검토 아이디어](#추가-검토-아이디어)

---

## 작성 규칙 (이 문서)

- **로드맵 범위**: 이 문서는 **마일스톤·아키텍처 원칙·단계별 목표** 중심. 세부 구현(함수·파일 경로 등)은 GitHub Issues·프로젝트 보드로 분리 권장. 본문의 파일/경로 언급은 참고용으로만 유지.
- **단일 참조(Single Source of Truth)**: 중요 결정(예: 일정 스키마 A vs B)은 **한 곳**에만 자세히 둔다. **결정 근거·비교**는 `docs/decisions/` 에 **ADR(Architecture Decision Record)** 로 분리 권장(예: `001-notice-schedule-schema.md`). 로드맵 본문에는 **결과만** 기입(예: "일정 스키마 A 적용"). 업데이트 시 누락 방지.
- **단계별 구조**: 각 단계는 `목표` → `할 일` → `검증`(해당 시) → `마일스톤` 순으로 작성한다.
- **할 일**: 한 항목당 한 주제. 하위 내용은 들여쓰기 리스트로 구분한다.
- **수정 시**: 로드맵 본문을 바꿀 때 **날짜·수정 내용·이유는 WORK_LOG에만 기록**한다. 로드맵 본문에는 변경 이력을 적지 않는다.
- **추가 아이디어**: 새로 떠오른 기능·변경은 "추가 검토 아이디어"에만 적고, 현재 단계가 끝날 때까지 단계 본문은 유지한다.
- **추가 검토 아이디어 작성**: 각 아이디어는 **고려 시점**을 반드시 명시한다. 해당 단계에서 검토할지, 그 이전/이후인지 한눈에 보이게 한다.
- **단계 완료 시 확인**: 어떤 단계가 끝나면(마일스톤 달성), 작업자(또는 에이전트)는 그 단계 또는 그 이전 단계에 해당하는 추가 검토 아이디어에 대해 사용자에게 검토 여부를 물어본다.

---

## 지금 상태


| 항목            | 내용                                                                                                                                                                                                               |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **현재 단계**     | **3단계 진행 중** (연세대 크롤러 레포 이식 및 작업 큐 연동)                                                                                                                                                                           |
| **이번 목표**     | Celery·Redis 연동 완료, 크롤러 Repository 분리·upsert·content_hash, trigger-crawl API, Railway 워커(Playwright 필요 시 Dockerfile), Sentry 워커 부착. 크롤러 소스: [SeaLion-hub/crawler](https://github.com/SeaLion-hub/crawler) 레포 기준. |
| **3단계 구현 현황** | 아래 [3단계 구현 현황](#3단계-구현-현황-진행-중) 표·[3단계 진행 과정](#3단계-진행-과정-코드-기준)(코드 기준·고려 사항 반영 현황) 참고.                                                                                                                           |
| **작업 기록**     | [WORK_LOG.md](./WORK_LOG.md)                                                                                                                                                                                     |
| **배포**        | 백엔드 Railway, 프론트 Vercel. 상세는 [DEPLOYMENT.md](./DEPLOYMENT.md). 프론트 폴더는 **6단계에서** 생성.                                                                                                                             |
| **주의사항**      | 바이브 코딩 시 실수 방지: [CAUTIONS.md](./CAUTIONS.md)                                                                                                                                                                     |


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
| **6단계 달력 UX**     | **한 화면 통합 + 시각적 구분 + 토글 필터**. 탭 분리 비권장(일정 충돌 확인이 달력 본질). 상세는 6단계 "달력 표시 방식 (6단계 진입 전 확정)" 참고.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |


---

## 미리 결정 필요 (진입 전)

각 단계 진입 전 또는 해당 단계 설계 시 결정해야 할 사항. 미리 정하지 않으면 리워크·혼란이 발생할 수 있음.

### 일정 스키마 (A vs B) — 단일 참조

**결과만 로드맵에 기입.** (예: "3단계: 일정 스키마 **A(DateTime 컬럼형)** 적용" 또는 "**B(dates JSONB 유지)** 적용")  
**결정 시점**: 3단계 DB 스키마 확정 전. 상세 비교·결정 근거는 [ADR 001 — Notice 일정 스키마](decisions/001-notice-schedule-schema.md) 참고.


| 단계      | 항목                                                    | 결정 시점               | 설명                                                                                                                                             |
| ------- | ----------------------------------------------------- | ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| 3단계     | College 목록·external_id                                | 3단계 시작 전            | 수집할 단과대/게시판 목록, College.external_id 정의. **College별 크롤러 모듈·목록 URL 매핑**을 config·시드에 문서화하고 구현과 함께 유지. (확정: external_id는 게시글 번호 우선, 없으면 URL path.) |
| 3단계     | ~~Notice.external_id~~ / ~~크롤 주기~~ / ~~content_hash~~ | —                   | **결정 완료.** 확정 사항 "3단계 확정(구현 원칙)" 참고.                                                                                                           |
| **3단계** | **Notice 일정 스키마 (A vs B)**                            | **3단계 DB 스키마 확정 전** | [ADR 001](decisions/001-notice-schedule-schema.md) 참고. 결정 후 3단계 마이그레이션·크롤러 매핑·4·5·6 할 일 일괄 적용.                                                 |
| 4단계     | User↔AI 매칭 규칙                                         | 4단계 스키마 설계 시        | User.profile_json(major, grade 등)와 ai_extracted_json(target_departments, target_grades)의 매칭 로직. "포함 여부" vs "정확 일치".                            |
| 4단계     | 학과·학년 값 형식                                            | 4단계 스키마 설계 시        | target_departments, target_grades 값 범위·형식 통일. User 프로필 값과 비교 가능하도록.                                                                            |
| 5단계     | 목록 API 페이지네이션                                         | 5단계 API 설계 시        | cursor vs offset, 기본 page_size. 6단계 무한 스크롤 설계에 영향.                                                                                             |
| 5단계     | 일정 API 필터 범위                                          | 5단계 API 설계 시        | year, month 외 day 또는 from/to 필요 여부. 6단계 주간 뷰 등에 영향.                                                                                            |


---

## 진행 시 예상 문제·대비 (블로커·병목)

개발을 진행할 때 예상되는 기술적·구조적 이슈와 대비 방안. 미리 결정 사항과 별도로, **구현 단계에서 반드시 고려**할 것.


| 구분                            | 예상 문제                                                                                                                                                            | 대비                                                                                                                                                                      |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Celery + 비동기 DB**           | Celery는 동기(sync), FastAPI·DB는 비동기(async). 태스크 안에서 매번 `asyncio.run()`으로 DB 접근 시 이벤트 루프·asyncpg 풀이 태스크마다 생성/해제되며 **커넥션 반환이 불완전**해질 수 있어 "Too many connections" 위험. | Celery 워커 전용 **동기 DB 세션(psycopg2)** 을 별도 구성하거나, 워커 생명주기에 맞춰 **커넥션 풀 관리**를 명시적으로 수행. 크롤러·AI 태스크에서 DB 접근 시 위 방식 중 하나 채택.                                                  |
| **429·지수 백오프**                | 대량 수집 시 AI 큐에 한꺼번에 쌓이면 Gemini RPM 초과 → 429 → 워커 실패.                                                                                                              | **rate_limit='10/m'** 필수. 실패한 태스크는 **지수 백오프**(2초→4초→8초)로 재시도하도록 Celery `retry_backoff=True` 등 **재시도 설정 반드시 구현**. (4단계 "Celery AI 태스크 속도 제한" 참고.)                        |
| **Playwright OOM**            | Chromium은 메모리 사용량이 크고, Railway 등 RAM 제한 환경에서 크롤러 여러 개 동시 실행 시 **OOM Kill**.                                                                                      | Playwright는 **정적 HTML 수집이 불가능할 때만** 사용. 실행 시 `**--no-sandbox`, `--disable-dev-shm-usage`** 필수. Celery **concurrency 1~2** 강제. (CAUTIONS·integrations.mdc 동일.)           |
| **AI False Positive**         | "애매하면 노출(True)" 규칙으로 중요한 공지 누락은 막지만, **무관한 공지 노출**로 피로도 증가.                                                                                                      | **6단계 핵심 UI**에 유저 피드백("나와 관련 없는 공지" 버튼) 포함. 클릭 시 is_manual_edited 또는 피드백 저장 → 베타테스트에서 AI 매칭 고도화용 데이터 수집. 어드민·검색 API 필터 보완은 별도.                                          |
| **Celery payload 크기**         | raw_html·이미지 데이터를 태스크 인자/반환값으로 넘기면 Redis 메모리·병목.                                                                                                                 | **데이터는 DB에만 저장.** 3→4 전달은 **notice_id만** 큐에 넣고, AI 워커는 DB에서 조회. (확정 사항 "3단계 확정" 참고.)                                                                                    |
| **Redis TLS (로컬 vs Railway)** | Railway Redis는 `rediss://`(TLS) 또는 암호 포함 URL 제공. `redis://`만 가정하면 연결 실패.                                                                                         | Celery broker_url 설정 시 **redis://·rediss://** 모두 대응. TLS 시 **ssl_cert_reqs** 등 옵션 적용. DEPLOYMENT·CAUTIONS 참고.                                                           |
| **방화벽·IP 차단**                 | 크롤러가 빠르게·동시에 요청하면 연세대 방화벽에서 DDoS로 간주·IP 차단 가능.                                                                                                                   | **Polite crawling**: 요청/페이지 간 **1초 딜레이**. 여러 단과대 **순차** 실행. **크롤 주기 6시간**(확정)으로 요청 빈도 완화. (Burst·Thundering herd·UA는 아래 행 참고.)                                          |
| **순간 동시 요청(Burst)**           | 6시간 정각에 여러 단과대·수십 페이지를 1~2초 안에 동시 요청하면 WAF가 트래픽 폭주/DDoS로 간주해 IP 밴 가능.                                                                                            | 요청 간 **최소 1~2초** 의도적 지연(time.sleep 등). **페이지네이션** 시 각 페이지 요청 간에도 동일 지연. 사람 클릭 속도와 유사하게. (crawl_service에서 이미 1초 적용.)                                                     |
| **Thundering Herd**           | 모든 단과대 크롤러가 정확히 같은 시각에 출발하면 서버에 한꺼번에 요청 집중.                                                                                                                      | **크롤 시작 시간 분산**: trigger-crawl에서 단과대별 **5분 간격** countdown 적용(공과대 0분, 상경 5분, 다음 10분 …). `apply_async(args=[code], countdown=i*300)`.                                     |
| **데이터센터 IP·User-Agent**       | Railway/AWS 등 IP는 데이터센터 IP로 분류. 대학 WAF가 특정 시기 해외·데이터센터 IP 차단할 수 있음. Python requests 기본 UA는 차단 확률 높음.                                                             | **실제 Chrome 브라우저 User-Agent** 사용. `crawler_config.CRAWLER_HEADERS`에 Chrome UA·Accept·Accept-Language 정의. 기본 UA 사용 금지.                                                   |
| **크롤링 의존성(단일 장애점)**           | 학교 전산처가 지속 크롤링을 비정상 트래픽으로 간주해 Railway IP를 예고 없이 차단할 수 있음. 크롤 중단 시 신규 공지 수집 불가.                                                                                   | 크롤 주기 **6시간** 적용. IP 차단 시 **수동 trigger-crawl**·모니터링(Sentry·로그)으로 조기 감지. 필요 시 Cron 주기 추가 완화 검토.                                                                          |
| **IP 차단(Timeout·403)**        | Railway 등 데이터센터 IP는 대학 WAF에서 차단·패턴 감지 시 밴되기 쉬움. 크롤러가 **Timeout·403 Forbidden**을 반복하면 IP 차단 가능성 의심.                                                               | 베타 오픈 후 Timeout·403 다발 시 IP 차단 의심. 문서에 있는 Playwright 도입 외 **프록시 로테이션**(ScraperAPI, ZenRows 등) 검토.                                                                       |
| **크롤러 HTTP·예외**               | **timeout 미지정** 시 서버 무응답이면 워커 Hang → 파이프라인 마비. **except Exception**으로 에러를 삼키면 Celery 재시도 불가·원인 파악 불가.                                                            | 모든 HTTP 요청에 **timeout**(예: 10초) 필수. **RequestException**은 raise. 파싱 오류는 **logging.exception()** 후 raise 또는 스킵. (CAUTIONS 참고.)                                           |
| **일정 스키마·5단계 성능**             | Notice가 **dates(JSONB)** 만 있으면 날짜 범위 쿼리 복잡·데이터 증가 시 달력 API 병목.                                                                                                   | [ADR 001](decisions/001-notice-schedule-schema.md) 참고. (A) 권장.                                                                                                          |
| **Push 알림 부재(리텐션)**           | 매칭 결과를 유저가 앱을 열 때만 보면, 가입 후 며칠 지나 존재를 잊기 쉬움.                                                                                                                     | 4단계에서 **매칭 시 알림 큐 enqueue**. 6단계에서 FCM·APNs·웹 푸시 연동. "맞춤 공지 도착" 푸시가 리텐션 핵심.                                                                                             |
| **깨진 링크(Dead Link)**          | 공지가 삭제·숨김되면 원문 링크 404 → 서비스 신뢰 하락.                                                                                                                               | **raw_html**로 앱 내 본문 표시(원문 실패 시 대체). 주기적 **링크 유효성 체크** 후 [마감됨]/[링크 만료] 라벨. (6단계 할 일 참고.)                                                                                |
| **Celery 침묵 실패·큐 정체**         | 셀렉터 변경 등으로 크롤/AI 태스크가 계속 실패하면 무한 재시도로 큐가 막힐 수 있음. 관리자 인지 전까지 신규 공지 누락.                                                                                           | Sentry로 실패 알람은 받되, **재시도 횟수 제한**(max_retries) 후 **Dead Letter Queue(실패 보관)** 로 보내 수동 검토. 무한 재시도 금지. (3·4단계 할 일에 max_retries·DLQ 라우팅 반영.)                                |
| **Redis 영속성**                 | Redis를 Celery broker·알림 큐로 사용 시 서버 재시작/장애 시 큐 유실. 알림 대기열 등 메시지 소실.                                                                                               | **Railway Redis 플랜 확인** 필수. 무료/저가형 플랜은 재시작 시 데이터 유실되는 경우 있음. 배포 전 **AOF 설정이 가능한 플랜인지** 확인. Redis는 **메시지 브로커**로 사용하므로 AOF 또는 RDB 백업 활성화. DEPLOYMENT에 Redis 영속성 설정 안내 포함. |


---

## 단계별 목표 기간


| 단계  | 목표 기간(주) | 비고                                       |
| --- | -------- | ---------------------------------------- |
| 1단계 | 완료       | —                                        |
| 2단계 | 완료       | —                                        |
| 3단계 | 1주-1.5주  | 3단계 시작 시 대략적 기간 설정 권장. 지연 시 WORK_LOG에 사유 |
| 4단계 | 2-3주     | 동일                                       |
| 5단계 | 1-2주     | 동일                                       |
| 6단계 | 3주       | 동일                                       |


---

## 1단계: 비동기 백엔드 뼈대 구축 및 Railway 개통

### 목표

단일 파일 의존 구조를 버리고, 계층형 아키텍처를 세운 뒤 Railway에 빈 서버를 배포한다.

### 할 일

- **진입점·패키지 구조 (고정)**
  - 진입점: `app.main:app`. 루트에 `app/` 패키지, 그 안에 `api/`, `core/`, `services/`, `repositories/`, `models/`, `schemas/` 배치.
  - DEPLOYMENT의 Start Command와 일치시켜 두고, 폴더 추가 시에도 이 구조 유지.
- **의존성·환경**
  - 배포용: `requirements.txt`에 버전 고정(pip-tools 권장). **현재는 1~3단계 배포용 최소 목록만** 포함(FastAPI·Celery·asyncpg·psycopg·BS4·requests·Auth·Sentry). 4단계에서 google-generativeai 등 추가 예정. 테스트/린트용은 `requirements-dev.txt` 분리. CI/배포는 `requirements.txt`만 사용.
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
  - 커밋 전 `.env` 실수 커밋 방지(pre-commit 또는 스크립트). 새 변수 추가 시 DEPLOYMENT 표 + `.env.example` 동시 수정.
- **에러·로깅 정책**
  - 공통 예외 핸들러: 비즈니스 예외 → HTTPException, 그 외 → 500 + 로그. `except Exception` 남용 금지.
  - 로깅 형식(구조화 로그 등) 1단계에서 한 번 정함.
- **모니터링 (Sentry)**
  - **1단계에서** Sentry DSN만 환경변수로 넣고, 백엔드 예외 발생 시 바로 슬랙/이메일 알림 받을 수 있게 세팅. 3·4단계에서 에러가 많이 나므로 미리 인프라만 갖춰 둠.
- **Railway CI/CD**
  - GitHub 푸시 시 자동 빌드·배포. Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
  - 3단계: **Celery 앱 진입점**(예: `app/worker.py`)·워커 프로세스 구성 후, 크롤러 전용 워커는 Playwright 미사용 시 **Nixpacks**로 동작 가능. Playwright를 쓰는 학과가 생길 때만 Dockerfile(Chromium) 사용.

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
  - **일정·달력 대비**: **일정 저장 방식**은 [ADR 001](decisions/001-notice-schedule-schema.md)에 따라 구현(결정 시점: 3단계 DB 스키마 확정 전). 현재 DB(005): dates/eligibility. user_calendar_events는 2단계에서 정의.
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
  - 코드로 정의한 테이블을 Railway DB에 적용하는 마이그레이션 세팅.

### 검증

- 앱 부팅 + `select(1)` 또는 마이그레이션 적용 성공을 CI에서 확인 가능하면 추가.

### 마일스톤

DB 클라이언트로 테이블 확인 가능. 앱 부팅 시 연결 검증. Auth 방식(구글 OAuth + JWT)과 User 스키마 문서화 완료.

---

## 3단계: 연세대 크롤러(레포 이식) 및 작업 큐 연동

### 목표

연세대 공지 수집을 **[SeaLion-hub/crawler](https://github.com/SeaLion-hub/crawler)** 레포 기반 자체 엔진으로 전환하고, 백그라운드(Celery)에서 공지를 수집·DB 저장하는 파이프라인을 완성한다.

### 3단계 구현 현황 (진행 중)

**할 일** 항목별 구현 여부(코드·인프라 기준). 규칙(계층 분리, CAUTIONS) 준수 여부 포함. 워커 DB는 **동기(psycopg)** 전용으로 전환 완료.


| 할 일 항목                             | 구현 여부 | 비고 (파일·규칙 준수)                                                                                                                                                                        |
| ---------------------------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Celery & Redis**                 |       |                                                                                                                                                                                      |
| └ Redis 연결 설정                      | ✅     | `app/core/config.py`에 `redis_url` (또는 `REDIS_URL`) 환경변수. `.env.example`에 REDIS_URL·CRAWL_TRIGGER_SECRET.                                                                             |
| └ Celery 앱 진입점(broker)             | ✅     | `app/worker.py`: Celery 앱·broker=Redis·result_backend. `rediss://`(TLS) 시 ssl_cert_reqs 적용.                                                                                          |
| └ Celery 크롤 태스크 정의                 | ✅     | `app/services/tasks.py`: `crawl_college_task(college_code)`, 동기 `crawl_college_sync`·`get_sync_session` 사용.                                                                          |
| └ Celery 워커 DB (동기 psycopg2)       | ✅     | `app/core/database_sync.py`: 동기 엔진·세션(psycopg). `get_by_external_id_sync`·`upsert_notice_sync`·`crawl_college_sync` 사용.                                                              |
| **크롤러 소스·레포 이식**                   |       |                                                                                                                                                                                      |
| └ SeaLion-hub/crawler 기준           | ✅     | 7개 모듈 `yonsei_engineering`~`yonsei_business`로 이식·Streamlit 제거. config에 모듈명·get_links/scrape_detail 매핑. 레포 readme 주의사항 준수.                                                            |
| **데이터 소스·수집 방식**                   |       |                                                                                                                                                                                      |
| └ httpx/requests+BS4 우선            | ✅     | 크롤러 모듈은 **requests + BeautifulSoup**. crawl_service에서 asyncio.to_thread로 호출. Playwright는 JS 필수 시에만.                                                                                  |
| └ 사이트별 크롤러 모듈 분리                   | ✅     | `app/services/crawlers/`: yonsei_engineering, yonsei_science, yonsei_medicine, yonsei_ai, yonsei_glc, yonsei_underwood, yonsei_business.                                             |
| **크롤러 설정(config) 분리**              | ✅     | `app/core/crawler_config.py`: 모듈명(yonsei_*), COLLEGE_CODE_TO_MODULE, url·get_links·scrape_detail.                                                                                    |
| **수집 대상·데이터**                      |       |                                                                                                                                                                                      |
| └ 제목·본문·이미지 URL/Base64·첨부          | ✅     | `yonsei_engineering.py`에서 제목, 본문(raw_html), images(URL+Base64), attachments 수집 후 Notice 저장.                                                                                          |
| └ 포스터 이미지 원본 URL                   | ⚠️    | `images` JSONB에 URL/Base64 저장. 별도 `poster_image_url` 컬럼은 005 마이그레이션에서 제거됨. 4단계 Multimodal 시 첫 이미지 또는 poster 전용 필드 복원 검토.                                                             |
| **데이터 정합성**                        |       |                                                                                                                                                                                      |
| └ 공지 유니크 (college_id, external_id) | ✅     | Notice에 `UniqueConstraint("college_id", "external_id")`. external_id는 no 우선·없으면 URL에서 추출.                                                                                            |
| └ upsert(재수집 시 업데이트)               | ✅     | `app/repositories/notice_repository.py`: `upsert_notice`, PostgreSQL `on_conflict_do_update`.                                                                                        |
| └ content_hash 저장·변경 감지            | ✅     | `crawl_service`: 제목+순수 본문 텍스트(get_text())로 sha256 계산·upsert 시 저장. 해시 변경·신규 시 `process_notice_ai_task.delay(notice_id)` enqueue. Repository `get_by_college_external_sync`로 기존 해시 비교. |
| └ 특정 기간/소스 재수집·복구 절차               | ✅     | `scripts/delete_notices_for_rerun.py` — `--college` 필수, `--before`/`--after`(YYYY-MM-DD) 옵션. 실행 후 POST /internal/trigger-crawl?college_code= 안내.                                     |
| **아키텍처 규칙(architecture.mdc)**      |       |                                                                                                                                                                                      |
| └ DB 접근은 repositories만             | ✅     | `crawl_service`는 college_repository·notice_repository만 사용. 크롤러 모듈은 순수 수집·파싱만.                                                                                                        |
| **Railway 워커**                     |       |                                                                                                                                                                                      |
| └ 기본(requests/httpx만)              | —     | 레포는 Playwright 없음. Nixpacks로 워커 동작 가능.                                                                                                                                               |
| └ Dockerfile (Playwright 필요 시)     | ❌     | Playwright 도입 시에만 Dockerfile·Chromium 설치 필요. OOM 방지: `--no-sandbox`, `--disable-dev-shm-usage`, `--concurrency=1`.                                                                   |
| **재시도·스케줄링**                       |       |                                                                                                                                                                                      |
| └ Celery autoretry_for             | ✅     | `crawl_college_task`에 `autoretry_for=(RequestException, ConnectionError, TimeoutError, OSError)`·`retry_backoff=True`·`retry_backoff_max=600` 적용.                                    |
| └ POST /internal/trigger-crawl     | ✅     | `app/api/internal.py`: X-Crawl-Trigger-Secret/Authorization/query 검증 후 `crawl_college_task.delay(college_code)` enqueue.                                                             |
| **모니터링**                           |       |                                                                                                                                                                                      |
| └ Sentry 워커 부착                     | ✅     | `app/worker.py` 로드 시 `SENTRY_DSN` 있으면 CeleryIntegration·LoggingIntegration 초기화.                                                                                                      |


**일정 스키마**: [ADR 001](decisions/001-notice-schedule-schema.md)에 따라 3단계 DB·4·5·6 구현.

### 3단계 진행 과정 (코드 기준)

상세 구현 여부는 위 [3단계 구현 현황](#3단계-구현-현황-진행-중) 표 참고. 고려 사항(진행 시 예상 문제·대비, 초석) 반영 여부는 동일 표의 비고 열과 [진행 시 예상 문제·대비](#진행-시-예상-문제대비-블로커병목) 참고.

**미반영·보완 권장**

- **max_retries·DLQ**: Celery 태스크에 max_retries 명시, 실패 시 DLQ 라우팅(추가 검토 아이디어 반영).
- **trigger-crawl 예외 처리**: POST /internal/trigger-crawl에서 apply_async 실패(Redis/broker 오류) 시 503 + 로그 반환.
- **워커 기동 시 init_sync_db**: 워커 로드 시 init_sync_db() 호출로 연결 실패 조기 감지(선택).

### 3단계에서 더 신경 쓸 부분 (초석)

나중에 예상되는 문제를 줄이기 위한 단단한 초석. 구현·문서화 우선순위.


| 우선순위 | 항목                                     | 내용                                                                                                                       |
| ---- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| 1    | **content_hash 변경 시 4단계 AI 큐 enqueue** | 크롤 시 기존 Notice 조회 후 content_hash 비교 → 변경·신규만 `process_notice_ai_task.delay(notice_id)`. 4단계는 notice_id만 받아 DB에서 조회 후 처리. |
| 2    | **일정 스키마 (A)/(B)**                     | [ADR 001](decisions/001-notice-schedule-schema.md)에 따라 3단계 DB·4·5·6 구현. (A) 권장.                                          |
| 3    | **task_id·college_code 로그·Sentry**     | Celery task_id·college_code를 로그 및 Sentry 태그로 남기면 4단계 디버깅·장애 대응 용이.                                                       |
| 4    | **College·config 일치**                  | college_code = trigger-crawl 인자 = College.external_id = config 키. College 추가·변경 시 시드와 crawler_config 동시 수정.              |
| 5    | **재수집·복구 절차**                          | `scripts/delete_notices_for_rerun.py --college=<code>` 후 POST /internal/trigger-crawl?college_code=.                     |
| 6    | **raw_html 계약 (3→4)**                  | Notice.raw_html = 크롤러 본문 HTML 그대로. 노이즈 제거는 content_hash 계산 시에만.                                                          |
| 7    | **크롤러 HTTP·예외 (타임아웃·재시도)**             | 모든 HTTP 요청에 **timeout** 필수. **RequestException**은 raise(재시도 동작). `except Exception` 후 정상 반환 금지.                          |


### 할 일 (상세)

- **크롤러 소스·이식 규칙 (레포 기준)**
  - **소스**: [SeaLion-hub/crawler](https://github.com/SeaLion-hub/crawler) — 연세대 단과대 공지 수집용 **독립형 파이썬 모듈 모음**. 학과(게시판)마다 **다른 모듈**을 import해 사용(engineering, science, medicine, ai, glc, underwood, business). 의존성: requests + BeautifulSoup4 (레포에는 Playwright 없음).
  - **이식 시 반드시 지킬 것**(레포 readme 기준): (1) **실제 공지 목록 URL을 인자로 주입** — 크롤러 함수 호출 시 해당 학과 목록 URL 전달. (2) **scrape_detail 등 추출 로직 수정 금지** — label_sibling, fr-view, 주석 처리 등 레포 로직 유지. (3) **반환 본문은 HTML** — 앱/API에서 표시 시 WebView 또는 HTML 렌더링 사용(표·서식 보존).
  - 레포 상세 반환 구조: `(title, date, content, images, attachments)` 튜플. images는 `[{ "type": "url"|"base64", "data": "...", "name": "..." }]`. content_hash 계산 시 본문은 이 HTML 기준으로 결정(미리 결정 필요 항목 참고).
- **College ↔ 크롤러 모듈·URL 매핑**
  - **config**(예: `crawler_config.py`) 또는 시드 데이터에 **College.external_id별** (1) 사용할 **크롤러 모듈명**(engineering / science / medicine / ai / glc / underwood / business), (2) 해당 학과 **공지 목록 URL** 정의. 레포는 학과마다 다른 모듈을 쓰도록 설계되어 있으므로 이 매핑이 필수.
- **Celery & Redis**
  - Railway에 Redis 추가. **Celery 앱 진입점**(예: `app/worker.py`)에서 broker=Redis, result backend 설정. Celery로 크롤링 전용 워커 구동. FastAPI(비동기)와 Celery(동기) 역할 분리.
  - AI 호출 태스크는 4단계에서 **rate_limit** 적용(아래 4단계 참고).
- **데이터 소스·수집 방식**
  - 레포 모듈은 **requests + BeautifulSoup**. DICEE에서 호출 시 **httpx**로 대체 가능하면 httpx 사용(메모리·일관성). 레포 이식 시 모듈별 `get_*_links(url)`, `scrape_*_detail(url)` 호출 흐름 유지.
  - **HTTP 타임아웃·예외**: 모든 HTTP 요청에 **timeout**(예: 10초) 필수. **RequestException**은 raise. `except Exception` 후 정상 반환 금지. (위 예상 문제·초석 참고.)
  - **User-Agent**: **crawler_config.CRAWLER_HEADERS**(실제 Chrome UA·Accept·Accept-Language) 사용. Python 기본 UA·데이터센터 IP 검열 차단 완화.
  - **Playwright**: 레포에는 없음. 연세대 게시판 중 **정적 HTML로 수집 불가한** 페이지만 나중에 Playwright 모듈 추가 시 Dockerfile·OOM 대비 적용(아래 "Railway 워커" 참고).
- **크롤러 설정(config) 분리**
  - CSS 선택자·URL·페이징은 **config 분리** 유지. 레포는 URL을 인자로 받으므로, DICEE config에는 **College별 목록 URL·모듈명**만 넣고 선택자 등은 레포 모듈 내부에 두면 됨. 사이트 개편 시 레포 쪽 수정 또는 config URL만 변경.
- **데이터 정합성 (변동·복구 대비)**
  - **공지 유니크: `(college_id, external_id)`** (2단계 코드 유지). 저장은 **upsert**: PostgreSQL `**insert(Notice).on_conflict_do_update(index_elements=['college_id','external_id'], set_={...})`** 사용. **NoticeRepository에 캡슐화**해 서비스 로직을 지저분하게 하지 않음. (확정 사항 "3단계 확정" 참고.)
  - **크롤링 DB 적재 시 건별 트랜잭션 분리**: 여러 공지 루프 적재 시 **단일 session.commit()으로 묶지 말고**, 건별(또는 소량 배치) commit으로 **부분 성공** 보장. 한 건 실패 시 전체 롤백 방지.
  - **content_hash**: **조회수·날짜·하단 배너 등 본문 외 요소를 제거**한 뒤, **제목 + 순수 본문 텍스트(get_text())**만으로 sha256 생성. raw_html 전체 해시 금지(동적 토큰·CSS 변경 시 불필요한 AI 재호출 방지). 해시 변경 시에만 4단계 AI 큐에 **notice_id만** enqueue. **본문 추출 시 타겟팅을 매우 정교하게**(가비지 노드 완전 제거) 유지. **베타 초기**에는 AI 호출 로그와 **content_hash 업데이트 빈도**를 면밀히 모니터링.
  - 문제 발생 시: 특정 기간/소스만 삭제 후 재수집 — `scripts/delete_notices_for_rerun.py --college=<code>` (옵션 `--before`/`--after` YYYY-MM-DD). 이후 POST /internal/trigger-crawl?college_code= 호출.
- **Tombstone(Soft Delete)·원본 삭제 공지 (3단계 후반 또는 4단계)**
  - 크롤 시 **이번 사이클 목록에 없는 external_id**에 해당하는 Notice는 **삭제하지 않고** **is_deleted=True**(또는 deleted_at)로 갱신(Tombstone). 원본 게시판에서 삭제된 공지를 DB에서 물리 삭제하지 않고 표시만 구분.
  - Notice 모델에 **is_deleted**(또는 deleted_at) 컬럼 추가. API·UI에서는 is_deleted=True인 공지에 "원본 출처에서 삭제된 공지입니다" 안내. (6단계 "깨진 링크" 문단과 구분: 링크 만료 vs 원본 삭제.)
- **Celery 태스크·Redis (payload·broker)**
  - **Payload**: 크롤러가 수집한 raw_html·이미지는 **Redis를 거치지 않음**. DB에만 저장. 4단계 AI 큐에는 **notice_id(또는 id 목록)만** 전달. AI 워커는 notice_id로 DB에서 조회. (진행 시 예상 문제 "Celery payload 크기" 참고.)
  - **Broker**: Celery broker_url은 **redis://·rediss://(TLS)** 모두 지원. Railway Redis가 TLS 사용 시 ssl_cert_reqs 등 적용. (DEPLOYMENT Redis 섹션 참고.)
- **Polite crawling (방화벽·IP 차단·Burst 방지)**
  - 요청/페이지 간 **1초 딜레이**(예: `time.sleep(1)`). **페이지네이션** 시 각 페이지 요청 간에도 동일 지연. 동시 요청 폭주(burst) 방지 — 사람 클릭 속도와 유사하게.
  - 여러 단과대 크롤은 **시작 시간 분산**(trigger-crawl에서 단과대별 5분 간격 countdown). Thundering herd 방지.
- **Celery 워커 DB (커넥션 고갈 방지)**
  - 워커(크롤러·AI 태스크)는 **동기 DB(psycopg2)** 전용 엔진/세션 사용. `asyncio.run()` 내부에서 asyncpg 사용 시 태스크마다 풀 생성/해제로 "Too many connections" 위험 있음. (진행 시 예상 문제·CAUTIONS 참고.)
- **계층형 아키텍처 준수**
  - **DB 접근은 repositories만**. 크롤러는 `repositories`(예: college_repository, notice_repository)를 통해 College 조회·Notice upsert. `services/crawlers`에서는 비즈니스 로직(파싱·흐름 제어)만 수행.
- **Railway 워커 (Playwright 필요 시에만 Dockerfile)**
  - **현재 레포는 requests+BeautifulSoup만 사용**하므로, 크롤러 전용 워커는 Nixpacks로 동작 가능. **Playwright를 도입하는 학과가 생길 때만** 아래 적용.
  - Playwright 사용 시: Nixpacks는 Chromium 미설치 → **직접 작성한 Dockerfile** 사용. `RUN playwright install --with-deps chromium` 명시.
  - **OOM 방지**: 브라우저 실행 시 `**--no-sandbox`, `--disable-dev-shm-usage`** 필수. Celery **concurrency 1~2** 제한. (CAUTIONS·integrations.mdc 동일.)
- **재시도·스케줄링**
  - Celery 태스크에 `autoretry_for` 등으로 재시도 설정. 실패 태스크는 **max_retries** 초과 시 **DLQ(Dead Letter Queue)** 로 전달해 수동 검토. 무한 재시도 금지. (예상 문제 "Celery 침묵 실패·큐 정체" 참고.)
  - **스케줄러: Railway Cron(또는 외부 Cron)** 으로 **POST /internal/trigger-crawl** 호출. 보안 키 검증 후 Celery 크롤 태스크 enqueue. **크롤 주기: 6시간마다**(확정). **단과대별 시작 분산**: 전체 크롤 시 `apply_async(countdown=i*300)`으로 5분 간격 stagger(Thundering herd 방지). Cron이 6시간마다 위 엔드포인트 호출. Celery Beat 미사용(비용).
- **모니터링**
  - **Sentry를 3단계부터** 백엔드·크롤러 워커에 부착. 워커 진입점에서 Sentry 초기화. 크롤러 실패 시 빨리 추적 가능. (6단계에서 프론트 에러 추가.)

### 검증

- 로컬 또는 CI에서 Redis 연결·Celery 워커 기동 후 `crawl_college_task.delay("engineering")` 호출 시 공대 게시판 수집·DB 저장 성공 여부 확인.
- (선택) 지정 시간에 trigger-crawl 호출 → 큐 적재 → 워커 처리 end-to-end 검증.

### 3단계 → 4단계 전 검크리스트 (데이터 품질 검수)

4단계 AI 비용·재처리 감소를 위해, **실제 데이터를 일정량 넣은 뒤** 아래를 확인한 뒤 4단계로 진입.

- **content_hash**: 실제 공지 약 **100건** 수준 적재 후 **content_hash 중복**이 발생하지 않는지 샘플 조회·로그 확인. (중복 시 변경 감지·AI enqueue 로직 오동작 가능.)
- **날짜 형식**: 크롤러별로 수집한 **published_at** 및 일정 관련 필드가 **깨지지 않고** 파싱·저장되는지 샘플 확인. (날짜 오기입 시 4·5단계 달력/필터 오동작.)

### 마일스톤

지정 시간마다 크롤러가(레포 모듈·College 매핑 기준) 최신 공지를 DB에 Raw로 저장(upsert·content_hash 적용). POST /internal/trigger-crawl로 Cron 연동 가능. **3단계→4단계 전 검크리스트**(데이터 품질 검수) 통과 후 4단계 진입. Playwright를 쓰는 학과가 있으면 해당 워커만 Dockerfile 기반 Railway에서 동작.

---

## 4단계: 티어링 기반 Multimodal AI 파이프라인

### 목표

AI 비용 절감 + 파싱 에러 원천 차단. **API 429로 워커가 죽지 않도록** 속도 제한 필수.

### 할 일

- **데이터 흐름 명확화**
  - **3→4 전달 (필수)**: 크롤러는 DB에만 저장. **4단계 AI 큐에는 notice_id(또는 id 목록)만** 전달. raw_html·이미지를 Redis 인자로 넣지 않음. **AI 워커는 notice_id로 DB에서 raw_html 등 조회** 후 처리. (확정 사항 "3단계 확정" payload 원칙.)
  - **AI 입력 전 raw_html 정제(필수)**: Notice.raw_html에는 Base64 인라인 이미지(`data:image/...`), `<style>`, `<script>` 등이 포함될 수 있어 **Gemini 토큰 초과·400 Payload 오류·비용 폭발** 위험. 3단계 저장 시점 또는 **4단계 AI 호출 직전**에 **Clean HTML** 생성(정규식/BS4로 `src="data:...` 제거, style/script 태그 제거) 후 Gemini에 전달.
  - **입력**: 위 Clean HTML 또는 본문 텍스트 추출 후 AI 전달. 포스터 분석 추가 시 poster_image_url 또는 images 활용.
  - **출력**: ai_extracted_json(자격요건), hashtags, **그리고 일정 데이터([ADR 001](decisions/001-notice-schedule-schema.md)에 따름)**. 4단계 워커는 자격요건·일정·hashtags만 UPDATE.
- **자격 요건·일정 스키마 (4·5·6단계 공유)**
  - **AI 출력용 Pydantic** 최소 필드: **target_departments** (List[str]), **target_grades** (List[str]), **deadline** (str, ISO), **event_title** (str), **event_start** / **event_end** (str, ISO). Gemini `response_schema`에 이 형태 강제 → 파싱 에러 원천 차단. 한 곳에서 정의하고 4·5에서 import.
  - **DB 저장**: [ADR 001](decisions/001-notice-schedule-schema.md)에 따라 저장. (A) 선택 시 deadline/event_* 컬럼에 ISO→datetime 저장, (B) 선택 시 dates 구조로 매핑.
  - 5·6단계 서비스 내부 달력·내보내기에서 동일 스키마 사용.
- **1차 키워드 필터**
  - 제목·본문에서 '점검', '단수' 등 필터 후 #일반 분류. 패턴은 config로 분리.
- **AI False Positive 지향 (프롬프트 규칙)**
  - 프롬프트에 **"판단이 애매하거나 조건이 명시되지 않은 경우, 해당 사용자에게 공지가 노출되도록(True) 설정하라"** 규칙을 명시. 놓쳐서 안 보이는 것보다, 불필요해도 한 번 더 보이는 것이 신뢰도 방어에 유리.
  - **방어적 피드백 루프**: 6단계 **"나와 관련 없는 공지" 버튼** 수집 데이터는 4단계 프롬프트 설계 시부터 **LangSmith·Few-shot 예제·매칭 로직 개선**에 활용할 계획을 반영. 오탐이 쌓여도 피드백으로 프롬프트/룰을 순환 개선.
- **Gemini Multimodal**
  - 중요 공지 중 포스터가 있으면 이미지를 Gemini 1.5에 직접 입력. 비공개 이미지는 크롤러에서 다운로드 후 bytes/base64 전달 검토.
- **Structured Output**
  - 위 자격 요건 Pydantic 모델을 Gemini `response_schema`에 전달해 JSON 형식 강제. `clean_json_string` 파싱 제거.
- **Celery AI 태스크 속도 제한 (필수)**
  - 공지가 한 번에 많이 쌓이면 Gemini 동시 호출로 **HTTP 429** 발생, 워커 실패.
  - **rate_limit='10/m'** (분당 10회). Gemini 무료 티어 15 RPM 대비 여유 두어 429 방지. 큐에 50건이 있어도 순차·제한적으로 호출.
  - `autoretry_for`와 별도로 **rate_limit** 반드시 명시. 할당량에 따라 `6/m`, `8/m` 등 조정 가능.
  - **429 재시도 시 지수 백오프**(예: 2초→4초→8초 대기) 적용. `retry_backoff=True`, `retry_backoff_max=600` 등으로 연속 429 시 즉시 재시도하지 않도록 함.
  - **max_retries** 초과 시 **DLQ(Dead Letter Queue)** 전달. 무한 재시도 금지. (예상 문제 "Celery 침묵 실패·큐 정체" 참고.)
- **재처리·롤백**
  - AI 처리 실패/잘못된 결과는 **재큐 또는 스킵 플래그**로 재처리 가능하게 설계.
  - **content_hash 변화 시에만 AI 재추출**: 3단계 크롤러에서 해시 변경 시에만 4단계 큐에 넣음. `is_manual_edited=True`인 공지는 AI로 덮어쓰지 않음.
- **LLMOps: 프롬프트 버저닝·A/B·Fallback**
  - **프롬프트 버저닝·의존성**: AI 프롬프트를 코드에 하드코딩하지 말고, DB 테이블(예: prompt_versions) 또는 설정 파일·LangSmith 등 **외부 저장**으로 분리하고 **버전 관리**. 수정 시 재배포 없이 버전 전환 가능하도록.
  - **A/B 테스트**: "A 프롬프트 vs B 프롬프트" 매칭률 측정이 가능하도록, 프롬프트 버전별 실행·결과 로깅(또는 이벤트) 설계.
  - **Fallback·Circuit Breaker**: Gemini 타임아웃·연속 실패 시 **재시도(Retry)** 후, 심각 장애 시 **룰 기반(키워드 매칭)** 등으로 임시 전환. API 다운 시에도 큐 전체 정지 방지.
- **Push 알림 파이프라인 (리텐션 핵심)**
  - AI 분류가 끝난 공지가 특정 user_id와 매칭되면 **알림 발송용 Celery 큐**로 이벤트 전달(notice_id, user_id 목록). "내 전공의 중요한 장학금 공지가 떴습니다" 같은 푸시 한 번이 앱 생사를 좌우.
  - 4단계: 매칭 결과 → **알림 큐 enqueue** 로직 추가(실제 발송은 5·6단계). 6단계에서 FCM(Android)·APNs(iOS) 또는 웹 푸시 연동.

### 마일스톤

불규칙한 포스터 공지도 AI가 JSON으로 분해해 DB에 에러 없이 저장. 대량 수집 시에도 429 없이 안정 동작. 매칭 시 알림 큐로 이벤트 전달 설계 반영.

---

## 5단계: 검색·프로필 매칭 API 완성

### 목표

정제된 DB로 **로그인한 유저**에게 맞는 공지를 골라주는 API 완성. (Auth·User는 2단계 구조, 구글 OAuth 사용.)

### 할 일

- **동적 쿼리·FTS·수동 검색**
  - SQLAlchemy로 검색어·필터에 따라 안전하게 쿼리 생성. PostgreSQL FTS 연동.
  - **수동 검색(Search)**: AI 맞춤 추천 외에 "토익", "교환학생", "예비군" 등 **키워드 검색** 수요 대비. **베타**: PostgreSQL **Full-Text Search(tsvector)** 로 제목·본문·해시태그 검색. 기본 LIKE 대신 FTS로 성능·정확도 확보. **추후** 트래픽 증가 시 Elasticsearch·Meilisearch 등 검색 엔진 도입 검토.
  - **GIN 인덱스**: ai_extracted_json(JSONB), 제목/본문 검색용 tsvector, hashtags 등에 Alembic 마이그레이션으로 GIN 인덱스 적용. 검색량 증가 시 성능 저하 방지.
- **맞춤 매칭**
  - 유저 프로필(전공, 학년, 군필, 학점 등)과 공지 자격 요건(JSON) 비교 로직을 `services/`에 구현. 4단계와 공유한 자격 요건 스키마 사용.
- **API·문서**
  - 공개 API는 `**/v1/` prefix**. 스키마 변경 시 기존 필드 삭제·이름 변경은 하지 않고, 추가만 하거나 새 버전(/v2/)으로 올리기.
  - `**GET /v1/users/me`**: JWT로 식별된 로그인 유저 프로필 조회 (5·6단계 프로필 매칭·설정 UI 필수).
  - 정렬·필터·페이지네이션 엔드포인트 완성, Swagger 문서화. 예시는 README/Postman에 정리.
- **일정·달력 API (핵심 기능)**
  - **user_calendar_events**: 2단계 스키마 유지 + **UniqueConstraint(user_id, notice_id)** 추가 (한 공지를 내 달력에 중복 추가 방지).
  - **추출 일정 목록 API**: **GET /v1/calendar/events?year=2026&month=3** (월별 쿼리). 응답: (1) 매칭된 공지 중 일정 있는 객체 배열([ADR 001](decisions/001-notice-schedule-schema.md) 기준), (2) user_calendar_events 배열. 프론트에서 두 배열 병합.
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
- **이용약관·개인정보처리방침 (필수)**
  - 대학생 대상 서비스 런칭 시 **서비스 이용약관(ToS)** 및 **개인정보처리방침** 동의 프로세스 반드시 구현. 회원가입/최초 로그인 시 동의 화면·체크·저장.
  - **민감정보**(학년·전공·GPA·군필 등) 수집 시: DB 저장 정책(단방향 암호화 검토), **탈퇴 시 영구 삭제** 등 법적 컴플라이언스 사전 확인. 학점 등 유출 시 타격이 크므로 보관·삭제 요건 정리.
- **유저 피드백 (6단계 핵심 UI)**
  - 베타테스트의 핵심은 **AI 매칭 로직 고도화용 실제 데이터 수집**. **"나와 관련 없는 공지"** 버튼을 6단계 핵심 UI로 포함. 클릭 시 is_manual_edited 또는 피드백 테이블 업데이트 → 이후 검색/매칭 로직 개선에 활용. (추가 검토가 아닌 본단계 할 일.)
- **데이터 검수·어드민(백오피스)**
  - AI 오분류(False Positive) 또는 잘못된 정보(예: 장학금 마감일 오기입)를 수동 보정하기 위해 **어드민 페이지** 계획. 개발자가 DB에 직접 SQL로 수정하는 상황을 줄이기 위함. is_manual_edited 플래그·일정/자격요건 수정 UI. (6단계 내 소규모 도입 또는 별도 마일스톤.)
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
- **Push 알림 (FCM·APNs·웹 푸시)**
  - 4단계에서 쌓은 **알림 큐**를 실제 기기로 발송. FCM(Android), APNs(iOS), 웹 푸시 중 대상 플랫폼에 맞춰 연동. 사용자가 앱을 열기 전에 "맞춤 공지 도착" 알림으로 리텐션 확보.
- **깨진 링크(Dead Link) 대비**
  - 학교 공지는 기한 후 삭제·숨김 처리되는 경우가 많음. 원문 링크 404 시 서비스 신뢰 하락 방지.
  - **앱 내 본문 표시**: 이미 저장한 **Notice.raw_html**로 원문이 삭제돼도 앱에서는 내용 확인 가능. 상세 화면에서 "원문 보기" 실패 시 저장 본문으로 대체 표시.
  - **링크 유효성**: 주기적 **Health-Check**(HEAD 요청 또는 가벼운 크롤)로 오래된 공지 링크 유효성 검사. 접속 불가 시 `link_expired=True` 등 플래그 또는 [마감됨]/[링크 만료] 라벨 UI 표시.
  - **원본 삭제 공지**: 원본 게시판에서 **삭제된 공지**는 **Tombstone(is_deleted)** 로 구분해 UI에 "원본 출처에서 삭제된 공지입니다" 안내. (3·4단계 Tombstone 설계 참고.)
- **프로덕트 애널리틱스(Telemetry)**
  - **유저 행동 이벤트**: "공지 노출", "원문 클릭", "북마크·내 달력 추가" 등 **이벤트 트래킹**. Amplitude / Mixpanel / PostHog 등 연동. 프론트–백엔드 **이벤트 규약** 정의(이벤트명·속성).
  - **지표 예**: 가입 후 N일 내 "자신과 관련된 장학금 공지 클릭 비율(Activation Rate)" 등. 베타 성공 지표·투자자 설득용.
- **모니터링**
  - Sentry는 3단계에서 이미 백엔드·워커에 부착. 6단계에서 **프론트 에러** 부착. 에러에 `task_id`, `notice_id` 등 컨텍스트 포함.

### 마일스톤

Vercel 배포 사이트에서 프로필 설정 후 자신에게 맞는 최신 공지를 에러 없이 확인 가능. **서비스 내부 달력**에서 추출된 일정(마감·행사) 확인 및 "내 달력에 추가" 가능. **.ics 내보내기**로 외부 달력에 저장 가능 → 베타 런칭 완료.

---

## 추가 검토 아이디어

- 새로 떠오른 기능·변경은 **여기에만** 적고, 현재 단계가 끝날 때까지 로드맵 본문은 유지.
- 로드맵 본문 수정 시 변경 이력은 **WORK_LOG에만** 기록한다.
- 단계별 목표 기간은 [단계별 목표 기간](#단계별-목표-기간) 표에 넣고, 지연 시 WORK_LOG에 사유 기록.
- 각 아이디어는 **고려 시점**을 명시. 단계가 끝나면 해당·이전 단계 검토 아이디어에 대해 사용자에게 확인 요청(규칙: `.cursor/rules/roadmap-and-worklog.mdc` 참고).

**3단계·크롤러 관련 (나중에 할 개선)**

- **3단계 마무리 또는 4단계 전** — **배치 조회**: `crawl_college_sync` 루프 내 `get_by_college_external_sync` 호출을 배치화(한 번에 college_id + external_id 목록 조회 후 맵으로 O(1) 조회). 공지 수 증가 시 DB 부하 감소.
- **3단계 마무리** — **워커 기동 시 DB 초기화**: `app/worker.py`에서 워커 기동 시 `init_sync_db()` 호출. 연결 실패를 빨리 감지.
- **3단계 마무리** — **trigger-crawl delay() 예외 처리**: POST /internal/trigger-crawl에서 `crawl_college_task.delay()` 실패(Redis/broker 오류) 시 503 + 로그.
- **크롤러 정리 시** — **공통 HTTP 래퍼**: timeout·RequestException 정책을 한 곳에서 적용하는 유틸 도입 시 7개 모듈 유지보수 완화. 파싱 실패 시 로깅 보강(URL/날짜 파싱 fallback 시 debug 로그).
- **3단계 마무리 또는 4단계** — **Redis 분산 락 (Crawl 동시성 제어)**: 동일 college_code에 대해 동시에 두 크롤이 돌지 않도록 `redis.lock(f"crawl_lock:{college_code}")` 형태로 분산 락 적용. Celery 태스크 진입 시 락 획득, 종료 시 해제. Race/데드락 이슈 보고 시 우선 적용.

**시니어·QA·인프라 피드백 (추가 검토)**

- **4단계 이후 또는 6단계 이후** — **비동기 큐 전환 (Celery → ARQ 등)**: Celery 대신 ARQ(Async Redis Queue) 등 비동기 큐 도입 검토. FastAPI와 동일한 async 스택으로 통일 시 crawl_college_sync 중복 제거·단일 비동기 파이프라인 구축 가능. 현재 Celery·동기 DB·Railway 워커 구성 확정 상태이므로 마이그레이션 시 배포·문서·워커 진입점 전반 변경 필요.
- **3단계 마무리 또는 크롤러 정리 시** — **크롤러 레지스트리·Base 클래스**: `importlib.import_module` 동적 로딩 대신 레지스트리 패턴 + BaseCrawler(ABC) 도입. get_links/scrape_detail 인터페이스 고정 시 Mypy·IDE·리팩터링에 유리. 동적 import 제거·타입 안전 개선.
- **4단계 또는 크롤러 정리 시** — **httpx·병렬 크롤링·Bulk Upsert**: 동기 requests + to_thread 대신 비동기 httpx 도입 검토. asyncio.Semaphore로 동시성 상한(예: 3~5) 두고 asyncio.gather 활용. 건별 upsert 대신 INSERT ... ON CONFLICT DO UPDATE 배치 실행 검토. 트레이드오프: Polite crawling(1초 딜레이·순차)과 충돌 가능. IP 차단·대학 서버 부하 고려. Bulk Upsert는 현재 건별 commit으로 부분 실패 보장 중.
- **3단계 마무리** — **CI PostgreSQL 서비스**: GitHub Actions CI에 `services: postgres` 추가, DATABASE_URL로 실제 DB 연결 후 Repository/Service 통합 테스트 실행. ci.yml 예시: postgres 15, health-check, `DATABASE_URL=postgresql+asyncpg://...`.
- **4단계 또는 배포 안정화 시** — **Health 확장·"마지막 성공 크롤" 모니터링**: 현재 /health는 DB·Redis만 확인. "크롤러가 0건만 반환하는 조용한 장애" 감지를 위해 crawl_runs 기반 "마지막 성공 크롤 시각"을 /health에 포함하거나, Sentry/Slack에 "최근 N시간 내 성공 건수 0" 알람 연동. GET /internal/crawl-stats가 이미 있으므로 모니터링 대시보드에서 해당 API 주기 호출로도 가능.

**기술·운영**

- **5·6단계 이후 또는 데이터 축적 후** — **데이터 수명 주기**: created_at 기준 **월별/학기별 파티셔닝** 검토. 오래된 데이터 **아카이빙·콜드 스토리지(S3 등)** 보관 정책. 인덱스 비대화·쿼리 저하·비용 방어.
- **1단계** — CI/CD: Ruff → Mypy → Pytest 자동 실행.
- **3단계 이후 ~ 6단계 직전** — API Rate Limit(클라이언트 방어): slowapi 등 백엔드 API Rate Limit 검토.
- **3단계 이후, 6단계 이전** — 토큰 무효화·로그아웃: Refresh 블랙리스트 또는 token_version 기반 무효화 검토.
- **3단계 이후** — 테스트 확장: GitHub Actions에 PostgreSQL, auth·Notice/크롤러 통합 테스트 추가.
- **5단계** — Repository → DTO 반환: user_repository 등 Pydantic 반환 검토(LazyLoading/Detached 위험 감소).
- **6단계 이후** — Observability: Correlation ID, structlog, Sentry request_id 태깅.
- **단계 완료 시마다** — 문서 정합성: 확정 사항 변경 시 ROADMAP·CAUTIONS·DEPLOYMENT 일치 유지.
- **6단계 이후** — AI False Positive 추가 고도화: is_manual_edited 기반 검색/필터 고도화, 어드민 확장. ("나와 관련 없는 공지" 버튼은 6단계 핵심 UI로 반영.)

**모바일·UX**

- **6단계 이후** — PWA(홈 화면 추가), 웹 푸시(새 공지 알림).
- **6단계** — 메타·OG 태그, Web Share API, 데이터 절약 모드, 접근성(WCAG), OAuth 모바일 플로우 검증.

