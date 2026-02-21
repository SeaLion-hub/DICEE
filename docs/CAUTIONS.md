# 바이브 코딩 시 주의사항 (CAUTIONS)

바이브 코딩 중 계획 이탈·변동·인프라 지뢰를 막기 위한 체크리스트. **코딩 전·중에** 이 문서를 한 번씩 보면 실수를 줄일 수 있다.

## 문서 링크

- [ROADMAP.md](./ROADMAP.md) — 전략·원칙·마일스톤·기둥·지표
- [ROADMAP_PHASES.md](./ROADMAP_PHASES.md) — 단계별 할 일·확정 사항·예상 문제·추가 검토
- [DEPLOYMENT.md](./DEPLOYMENT.md)
- [WORK_LOG.md](./WORK_LOG.md)

---

## 목차

- [Cursor 코딩 규칙](#cursor-코딩-규칙)
- [1. 계획·단계 관련](#1-계획단계-관련)
- [2. 구조·설정·시크릿](#2-구조설정시크릿)
- [3. 의존성·빌드](#3-의존성빌드)
- [4. 에러 처리·로깅·모니터링](#4-에러-처리로깅모니터링)
- [5. DB·마이그레이션](#5-db마이그레이션)
- [6. 크롤러·워커 (3단계)](#6-크롤러워커-3단계)
- [7. AI 파이프라인 (4단계)](#7-ai-파이프라인-4단계)
- [8. Auth·API (2·5·6단계)](#8-authapi-256단계)
- [9. 배포·인프라](#9-배포인프라)
- [10. 바이브 코딩 습관](#10-바이브-코딩-습관)
- [요약: 코딩 전 30초 체크](#요약-코딩-전-30초-체크)

---

## Cursor 코딩 규칙

바이브 코딩 시 자동 적용되는 규칙은 `.cursor/rules/`에 있다. 문법·계층·연동 실수를 줄이려면 코드 생성 전에 한 번 확인한다.

- **`tech-stack.mdc`**: SQLAlchemy 2.0(비동기)·Pydantic v2·Depends 강제, async 라우터에서 sync 블로킹 금지
- **`architecture.mdc`**: Router→Service→Repository 관심사 분리, 호출 방향 엄수, 예외는 Router/전역 핸들러에서만 HTTP로 변환
- **`integrations.mdc`**: Gemini Structured Output만 사용, Celery `rate_limit`·`asyncio.run` 래핑, Playwright 옵션·concurrency 제한
- **`user-actions.mdc`**: **사용자(나)가 직접 해야 할 설정/실행은 항상 명시**하고, **다음 단계로 넘어가기 전에 사용자 확인** 요청

---

## 1. 계획·단계 관련

| 주의사항 | 설명 | 대응 |
|----------|------|------|
| **현재 단계만 집중** | 다른 단계 기능을 미리 넣으면 의존성·복잡도만 늘어남. | ROADMAP "지금 상태"에서 현재 단계 확인. 이번 단계 목표만 달성할 것. |
| **새 기능·아이디어** | 코딩하다 새로 생각난 기능을 바로 구현하지 말 것. | ROADMAP 맨 아래 "추가 검토 아이디어"에만 적어 두고, 현재 단계 완료 후 검토. |
| **로드맵 본문 수정** | 단계 내용을 바꿀 때 이유 없이 고치면 나중에 혼란. | 수정 시 **날짜, 수정 내용, 이유**를 한 줄이라도 기록(ROADMAP 또는 WORK_LOG). |
| **WORK_LOG 미기록** | 나중에 "그때 뭘 바꿨지?" 복기 불가. | 작업 세션 끝날 때마다 **실제로 한 수정**을 WORK_LOG에 1~3줄이라도 기록. |
| **프론트 폴더** | 6단계 전에 `frontend/` 만들면 구조만 흐려짐. | 프론트엔드 폴더는 **6단계에서** 생성. 그 전까지 백엔드만. |

---

## 2. 구조·설정·시크릿

| 주의사항 | 설명 | 대응 |
|----------|------|------|
| **진입점 변경** | `main:app` vs `app.main:app` 혼동 시 배포·로컬 실행이 깨짐. | **진입점은 `app.main:app` 고정**. DEPLOYMENT Start Command와 일치. 루트에 `app/` 패키지. |
| **폴더 구조** | `api/`, `core/`, `services/` 등 위치를 맘대로 바꾸면 import 전부 깨짐. | ROADMAP 1단계 "계층형 디렉터리" 유지. 새 폴더는 `app/` 안에 추가. |
| **환경변수 하드코딩** | API 키·URL을 코드에 넣으면 커밋 시 유출. | 모든 설정은 **환경변수**. `.env.example`에는 **키 이름만**. 값은 로컬 .env·Railway Variables. |
| **.env 커밋** | 실수로 .env를 푸시하면 시크릿 유출. | 커밋 전 `.env` 포함 여부 확인. pre-commit 또는 스크립트로 방지. |
| **새 환경변수** | 코드에만 넣고 문서 안 바꾸면 배포·협업 시 누락. | 새 변수 추가 시 **DEPLOYMENT 표 + .env.example** 동시 갱신. |

---

## 3. 의존성·빌드

| 주의사항 | 설명 | 대응 |
|----------|------|------|
| **버전 미고정** | `pip install` 할 때마다 다른 버전 설치되면 "로컬에선 되는데 Railway에서 터짐". | `requirements.txt`에 **버전 고정**. pip-tools 권장. |
| **dev 패키지가 배포에 섞임** | 테스트/린트 전용 패키지가 production 빌드에 들어가면 불필요한 충돌·용량. | **requirements-dev.txt** 분리. CI/배포는 **requirements.txt**만 사용. |

---

## 4. 에러 처리·로깅·모니터링

| 주의사항 | 설명 | 대응 |
|----------|------|------|
| **except Exception** | 모든 예외를 잡고 로그만 남기면 데이터 무결성 깨진 채로 흐름이 계속됨. | **비즈니스 예외 → HTTPException**. 그 외는 500 + 로그. `except Exception` 남용 금지. |
| **Sentry 미부착** | 3·4단계에서 에러가 많이 나는데 6단계까지 기다리면 디버깅 지연. | **1단계에서 Sentry DSN** 세팅. 3단계에서 워커까지 확장. 에러 알림을 미리 받을 것. |
| **에러 메시지에 컨텍스트 없음** | "Error"만 남기면 원인 추적 불가. | 에러 로그/Sentry에 `task_id`, `notice_id`, `college_id` 등 **컨텍스트** 포함. |

---

## 5. DB·마이그레이션

| 주의사항 | 설명 | 대응 |
|----------|------|------|
| **로컬 vs Railway DB 혼동** | 로컬에서 마이그레이션만 돌리고 Railway는 안 돌리면 스키마 불일치. | **환경 정책** 명확히: 로컬 DATABASE_URL / Railway DATABASE_URL. 배포 시 마이그레이션 실행 주체·시점 정해 둠. |
| **마이그레이션 역방향** | down 마이그레이션으로 롤백하면 데이터 유실·충돌. | 마이그레이션은 **순서대로, up만** 적용. 롤백 필요 시 새 마이그레이션으로 복구. |
| **Raw SQL 문자열 조합** | 조건 추가할 때마다 문자열로 SQL 만들면 인젝션·버그 위험. | **ORM(SQLAlchemy)** 로만 쿼리. 동적 조건은 `where()`, `and_()` 등으로 조합. |

---

## 6. 크롤러·워커 (3단계)

| 주의사항 | 설명 | 대응 |
|----------|------|------|
| **Celery payload (큐에 큰 데이터)** | raw_html·이미지를 태스크 인자/반환값으로 넘기면 Redis 메모리·병목. | **데이터는 DB에만 저장.** 4단계 AI 큐에는 **notice_id만** 전달. AI 워커는 DB에서 조회. ROADMAP 확정 "3단계 확정" 참고. |
| **content_hash 노이즈** | HTML 그대로 해시하면 조회수·날짜·동적 토큰 변경마다 해시 바뀌어 **불필요한 AI 재호출** 폭증. 본문 하단 동적 요소(조회수·오늘의 식단 등) 포함 시 내용 동일해도 해시 변경. | BeautifulSoup으로 **조회수·날짜·배너 등 제거** 후 **제목+순수 본문 텍스트(get_text())**만 sha256. **본문 추출 시 타겟팅 정교화**(가비지 노드 완전 제거). **베타 초기**에는 AI 호출 로그·**content_hash 업데이트 빈도** 모니터링. ROADMAP 확정 "3단계 확정" 참고. |
| **Polite crawling·IP 차단** | 빠르게·동시에 요청하면 연세대 방화벽에서 IP 차단 가능. | **요청/페이지 간 1초 딜레이.** 여러 단과대 **순차** 실행(concurrency=1 또는 순차 enqueue). |
| **Timeout·403 시 IP 차단 의심** | Railway 등 데이터센터 IP는 대학 WAF에서 차단·패턴 감지 시 밴되기 쉬움. 크롤러가 **Timeout·403 Forbidden**을 반복하면 IP 차단 가능성 의심. | 베타 오픈 후 Timeout·403 다발 시 **IP 차단** 의심. Playwright 도입 외 **프록시 로테이션**(ScraperAPI, ZenRows 등) 검토. |
| **Redis TLS (로컬 vs Railway)** | Railway Redis는 `rediss://`(TLS) 제공. `redis://`만 가정하면 연결 실패. | Celery broker_url에서 **redis://·rediss://** 모두 대응. TLS 시 **ssl_cert_reqs** 등 적용. DEPLOYMENT Redis 참고. |
| **Upsert 구현** | "있으면 갱신"을 ORM만으로 하면 까다로움. | PostgreSQL **`insert().on_conflict_do_update(index_elements=[...], set_={...})`** 사용. **NoticeRepository에 캡슐화.** ROADMAP 3단계 할 일 참고. |
| **Playwright OOM** | Railway에서 Chromium 여러 개 띄우면 RAM 초과로 OOM Kill. **정적 HTML 수집 불가 시에만** Playwright 사용. | 브라우저 옵션 **`--no-sandbox`, `--disable-dev-shm-usage`** 필수. **Celery concurrency 1~2**로 제한. |
| **Celery + 비동기 DB 풀** | 태스크 안에서 `asyncio.run()`으로 asyncpg 사용 시 커넥션 반환이 불완전해 "Too many connections" 위험. | 워커 전용 **동기 DB(psycopg2)** 사용. asyncpg는 FastAPI 웹만. ROADMAP "진행 시 예상 문제·대비" 참고. |
| **크롤러 설정 하드코딩** | 사이트 개편 시 CSS 선택자·URL을 코드에서 매번 수정·재배포해야 함. | **선택자·URL 패턴·페이징 규칙**은 config 분리. 레포는 URL 인자로 받으므로 config에 College별 URL·모듈명만. |
| **중복 수집** | 재실행 시 같은 공지가 두 번 들어감. | **(college_id, external_id)** 유니크. 저장은 **upsert**(on_conflict_do_update). |
| **실패 시 복구 없음** | 잘못된 데이터 대량 적재 시 되돌릴 방법이 없음. | 특정 기간/소스만 **삭제 후 재수집**하는 스크립트 또는 절차를 두기. |
| **Nixpacks로 워커 배포** | Playwright 워커를 Nixpacks로 올리면 "Browser executable not found". | Playwright 워커는 **Dockerfile**로만 빌드. `RUN playwright install --with-deps chromium` 포함. |
| **로컬에서 Celery + Railway Redis URL** | `.env`에 `REDIS_URL=redis://...redis.railway.internal...` 넣고 로컬 PC에서 워커를 돌리면 `getaddrinfo failed`. | **로컬 워커**는 로컬 Redis 사용: `REDIS_URL=redis://localhost:6379/0` 또는 REDIS_URL 비우기. Railway 내부 URL은 **Railway 서비스끼리**만 사용. |
| **Windows에서 Celery prefork** | Windows에서 `celery worker` 기본(prefork) 실행 시 billiard 세마포어 `PermissionError`/`OSError` 발생. | **Windows**에서는 `celery -A app.worker worker -l info --pool=solo` 로 실행. |
| **Tombstone(Soft Delete) 부재** | 크롤 목록에서 사라진(삭제/비공개) 공지를 DB에서 어떻게 할지 코드 없음. 사용자에게 '없는 페이지' 추천 가능. | **3단계 마무리** 시 **is_deleted**(Tombstone) 구현 권장. ROADMAP "Tombstone·원본 삭제 공지" 참고. |
| **다중 워커·visibility_timeout** | 크롤 태스크가 장시간이면 Redis visibility 타임아웃 만료 후 같은 메시지가 다른 워커에 재전달될 수 있음. | **broker_transport_options = {"visibility_timeout": 3600}**(1시간) 등 넉넉히 설정. DEPLOYMENT·worker.py 참고. |

---

## 7. AI 파이프라인 (4단계)

| 주의사항 | 설명 | 대응 |
|----------|------|------|
| **AI 태스크에 raw_html 전달** | 3→4 전달 시 raw_html·이미지를 큐 인자로 넣으면 Redis 메모리·병목. | **notice_id만** 큐에 넣고, AI 워커는 **DB에서 raw_html 등 조회**. ROADMAP 확정 "3단계 확정"·4단계 데이터 흐름 참고. |
| **429 폭주** | 큐에 공지가 많이 쌓인 상태에서 워커가 Gemini를 동시에 많이 호출하면 429. | Celery 태스크에 **rate_limit**(예: `10/m`) 반드시 명시. **429 재시도 시 지수 백오프**(2초→4초→8초) 적용. |
| **AI 환각·정보 누락** | 핵심 조건(학과·학년 등)을 AI가 놓치면 사용자 피해. | 프롬프트에 **"애매하면 노출(True)"** 규칙 명시. False Positive 지향 설계. |
| **자격 요건 스키마 불일치** | 4단계 AI 출력 JSON과 5단계 매칭 로직이 필드명·형식이 다르면 매칭 깨짐. | **자격 요건 Pydantic 모델을 한 곳에서 정의**. 4·5단계가 동일 스키마 import. 스키마 변경 시 4·5 함께 수정. |
| **파싱으로 JSON 추출** | AI 응답에서 `re.search`·`find('{')`로 JSON을 긁지 말 것. | **Structured Output**(Gemini response_schema에 Pydantic 전달)으로만 JSON 받기. |
| **재처리 불가** | AI가 잘못 처리한 공지를 다시 돌릴 방법이 없음. | **재큐** 또는 **스킵 플래그**로 재처리 가능하게 설계. |

---

## 8. Auth·API (2·5·6단계)

| 주의사항 | 설명 | 대응 |
|----------|------|------|
| **OAuth 핸드쉐이크 미정** | 프론트(Vercel)와 백(Railway)이 다른 도메인인데, 토큰 주고받는 방식을 6단계에서만 정하면 CORS·보안으로 일주일 낭비. | **2단계에서** "프론트가 code를 백으로 전달 → 백이 JWT 발급 → body JSON vs HttpOnly Cookie" 중 하나로 **핸드쉐이크 확정**. CORS·Credentials를 그에 맞춰 설계. |
| **토큰 무효화(로그아웃) 원자성** | 로그아웃 시 DB와 Redis가 따로 실패하면 좀비 세션·일관성 깨짐. | **순서 보장**: DB(Refresh 버전 증가) 선행 → Redis(Blocklist 등록). Redis 실패 시 예외 발생·클라이언트 재시도 가능. DB는 이미 반영되어 Refresh 무효화됨. auth_service.logout_user 참고. |
| **API 버전 없음** | 나중에 필드명 바꾸면 프론트 연쇄 수정. | 공개 API는 **`/v1/` prefix**. 기존 필드 삭제·이름 변경 금지. 추가만 하거나 /v2/로. |
| **ALLOWED_ORIGINS 누락** | 6단계에서 프론트 도메인을 안 넣으면 CORS 에러. | 6단계 연동 전에 Railway Variables에 **ALLOWED_ORIGINS**(Vercel URL) 설정. |

---

## 9. 배포·인프라

| 주의사항 | 설명 | 대응 |
|----------|------|------|
| **비용·리소스 무시** | 웹+DB+Redis+워커 동시 운영 시 Railway 한도·비용을 안 보면 갑자기 과금·다운. | DEPLOYMENT "비용·리소스" 참고. 플랜별 제한·월 상한을 주기적으로 확인. |
| **Start Command 불일치** | 로컬은 `main:app`, Railway는 `app.main:app` 처럼 다르면 배포만 실패. | **DEPLOYMENT와 ROADMAP의 진입점·Start Command** 와 코드가 일치하는지 확인. |
| **Redis SPOF** | Blocklist와 Trigger 락은 **풀 분리**로 장애 전파를 완화하지만, **단일 Redis 인스턴스는 SPOF**. 인스턴스 다운 시 인증·락 모두 불가. | 문서화·모니터링 필수. 필요 시 Redis HA/Sentinel 등은 별도 검토. |
| **분산 락 좀비 복구** | 워커 하드 킬·네트워크 파티션 시 `finally`가 실행되지 않아 락이 해제되지 않을 수 있음. **TTL이 유일한 복구 수단**. Compare-and-del은 "정상 종료 시 타인 락 삭제 방지"용. | `TRIGGER_LOCK_TTL_SECONDS`는 최대 크롤 소요 시간보다 크게, 그러나 죽은 워커가 락을 붙잡는 시간은 짧게 유지. 워커 정상 완료 시에는 반드시 compare-and-del로 조기 해제. |

**배포 직전 10초 체크리스트**

1. **크롤러에 무한정 기다리는 HTTP 통신이 있는가?** → `requests.get`에 `timeout` 누락 여부 grep. (현재 전 크롤러 timeout=10 적용. 유지.)
2. **조용히 넘기는 예외(pass)가 핵심 데이터를 훼손하지 않는가?** → `_parse_published_at`, `_external_id_from_url` 등에서 pass 제거·구체 예외+로그 연결 여부 확인.
3. **.env.example과 Railway Variables 동기화되었는가?** → DEPLOYMENT 표·.env.example에 필수 변수 목록 명시. 배포 시 Railway Settings와 대조(DATABASE_URL 포맷 `postgresql+asyncpg://`, JWT_SECRET, GOOGLE_CLIENT_ID/SECRET 등).

---

## 10. 바이브 코딩 습관

| 주의사항 | 설명 | 대응 |
|----------|------|------|
| **한 번에 여러 단계** | 1단계 하다가 2단계 DB 모델까지 만들어 버리면 검증·롤백이 어려움. | **한 단계 마일스톤을 달성한 뒤** 다음 단계로. WORK_LOG로 "이번에 한 것" 경계 유지. |
| **검증 생략** | "동작하는 것 같다"로 넘어가면 나중에 회귀 버그. | 단계 완료 시 **자동 검증**(CI에서 health 체크, 마이그레이션 성공 등)을 가능한 범위에서 추가. |
| **문서 업데이트 안 함** | 코드만 바꾸고 ROADMAP·DEPLOYMENT를 안 고치면, 나중에 다른 환경에서 재현 불가. | 구조·진입점·환경변수·정책이 바뀌면 **해당 문서를 즉시** 갱신. |
| **하드코딩** | URL·키워드·선택자를 코드에 박아 두면 사이트/정책이 바뀔 때마다 코드 수정. | 설정 가능한 것은 **config·환경변수·DB**로 분리. |

---

## 요약: 코딩 전 30초 체크

1. **지금 단계**가 ROADMAP과 맞는가?
2. **진입점** `app.main:app`, **폴더** `app/` 안 유지하는가?
3. **새 환경변수** 썼으면 DEPLOYMENT + .env.example 갱신했는가?
4. **except Exception** 없이, **Sentry** 붙여 두었는가?
5. **Playwright** 쓸 때 브라우저 옵션 + **concurrency 1~2** 인가?
6. **자격 요건 스키마**는 4·5단계 공유, **API**는 `/v1/`, **OAuth**는 2단계 핸드쉐이크 확정했는가?
7. 작업 끝나면 **WORK_LOG**에 한 줄이라도 썼는가?

이 문서는 ROADMAP·비판 반영 내용을 바탕으로 작성됨. 수정·추가 시 WORK_LOG에 기록할 것.
