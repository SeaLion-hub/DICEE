# 작업 로그 (WORK_LOG)

## 목차

- [작성 규칙](#작성-규칙)
- [작성 형식](#작성-형식)
- [2026-02-17](#2026-02-17)
- [2026-02-16](#2026-02-16)
- [템플릿 (새 날짜에 복사)](#템플릿-새-날짜에-복사)

---

## 작성 규칙

- 예정이 아니라 **실제로 한 수정**만 기록
- 가능하면 **파일/디렉터리**와 **이유/결과**를 1줄로 함께 남기기

## 작성 형식

- `- [단계 또는 영역] 무엇을 했는지 (어떤 파일/기능). 왜 또는 결과 한 줄.`

---

## 2026-02-16

- [Cursor 규칙] .cursor/rules/user-actions.mdc 추가 — 사용자가 직접 설정·실행할 부분은 항상 명시하고, 진행 전 사용자 확인 요청. CAUTIONS에 user-actions 안내 추가.
- [로드맵] 일정·달력 핵심 기능 구체 반영 — 2단계 Notice·user_calendar_events 설계, 4단계 추출 스키마에 일정 필드, 5단계 일정 API·.ics·구글 캘린더 내보내기, 6단계 서비스 내부 달력 UI·내보내기 UI.
- [Cursor 규칙] .cursor/rules/ 에 tech-stack.mdc, architecture.mdc, integrations.mdc 추가·보완. SQLAlchemy 2.0·Pydantic v2·Depends·async 블로킹 금지 / 계층 분리·호출 방향 / Gemini·Celery rate_limit·Playwright. docs/CAUTIONS.md 에 Cursor 규칙 안내 문장 추가.
- [로드맵·문서] Sentry 1단계, OAuth 핸드쉐이크 2단계, Playwright OOM(옵션·concurrency) 3단계 반영. docs/CAUTIONS.md 추가 — 바이브 코딩 시 주의사항·체크리스트 전부 정리. ROADMAP·DEPLOYMENT·README 링크 반영.
- [로드맵·문서] Auth 구글 우선으로 변경. ROADMAP·DEPLOYMENT·README 전면 반영 — 검증/롤백/환경/시크릿/에러/upsert/데이터흐름/4·5 스키마 공유/Sentry 3단계/의존성/API 버전/진입점/비용 등 비판 반영.
- [문서] README, ROADMAP, DEPLOYMENT, WORK_LOG 가독성 개선 — 소제목·테이블·문단 나누기, 중복 정리.
- [문서] README.md 정리 — 아이디어(문제/목표), MVP(SeaLion-hub/DICE test) 참조, 이 레포 재구축 맥락, docs 링크, 로컬 실행 예정.
- [로드맵] docs/ROADMAP.md 전면 수정 — Playwright Railway Dockerfile, Auth(OAuth+JWT) 2단계 반영, Celery AI 태스크 rate_limit 명시. 인프라·인증·429 대응 누락 보완.
- [배포] docs/DEPLOYMENT.md 추가 — Railway(백엔드)·Vercel(프론트) 기준 설정 정리. .cursor/rules에 배포 환경 기본 가정 및 "프론트 폴더는 6단계에서 생성" 명시.

---

## 2026-02-17

- [로드맵·비판 반영] 4가지 검토 사항 반영 — (1) 3단계: API 역공학 사전 조사(httpx 우선), 크롤러 설정(선택자·URL) config 분리. (2) 4단계: AI False Positive 지향(애매하면 노출) 프롬프트 규칙, 429 지수 백오프. CAUTIONS·integrations.mdc 동기화.
- [로드맵·결정 사항] 3·4·5단계 반드시 정할 항목 반영 — ROADMAP.md: 공지 유니크 (college_id, external_id), 스케줄러 Railway Cron + /internal/trigger-crawl, 4단계 입출력·자격요건 스키마·rate_limit 10/m, 5단계 user_calendar UniqueConstraint·일정 API year/month 스펙. DEPLOYMENT.md Cron 섹션 및 CRAWL_TRIGGER_SECRET, .env.example REDIS_URL·CRAWL_TRIGGER_SECRET 추가.
- [2단계 모델] Notice에 hashtags(JSONB) 컬럼 추가. UserCalendarEvent에 UniqueConstraint(user_id, notice_id) 추가. alembic/versions/004_add_hashtags_and_user_calendar_unique.py 마이그레이션 생성.
- [1단계] requirements.txt, requirements-dev.txt 생성. fastapi, uvicorn, sqlalchemy, alembic, asyncpg, pydantic-settings, sentry-sdk 버전 고정.
- [1단계] app/ 패키지 및 계층형 디렉터리 구조 생성 (api/, core/, services/, repositories/, models/, schemas/).
- [1단계] app/main.py — FastAPI 앱, /health 라우터, 전역 예외 핸들러, Sentry 초기화(lifespan).
- [1단계] app/api/health.py — GET /health → 200 + {"status":"ok"}.
- [1단계] app/core/config.py — pydantic-settings로 SENTRY_DSN, DATABASE_URL 환경변수 로드.
- [1단계] .env.example, .gitignore 생성. DEPLOYMENT.md에 SENTRY_DSN 환경변수 추가.
- [1단계] 로컬 검증 완료: uvicorn app.main:app 실행 후 GET /health → {"status":"ok"}. Railway 배포는 사용자 진행 예정.
- [1단계] Railway 배포 및 마일스톤 달성: Railway 도메인에서 GET /health → 200 + {"status":"ok"} 확인 완료. 1단계 완료.
- [2단계] app/core/database.py — 비동기 엔진, get_db, init_db, verify_db_connection. CAUTIONS 준수: 연결 실패 시 Sentry 보고 후 sys.exit(1).
- [2단계] app/main.py — lifespan에 init_db·verify_db_connection, CORS 미들웨어 추가.
- [2단계] app/models/ — Base, College, Notice, User, UserCalendarEvent. SQLAlchemy 2.0 Mapped·mapped_column. (college_id, external_id), (provider, provider_user_id) 유니크.
- [2단계] app/schemas/ — UserBase, UserCreate, UserResponse, UserProfile, TokenPayload, TokenResponse, RefreshTokenPayload.
- [2단계] alembic 초기화, env.py 비동기 설정, versions/001_initial.py 수동 생성.
- [2단계] app/repositories/user_repository.py — get_by_provider_uid, upsert_by_provider_uid.
- [2단계] app/services/auth_service.py — exchange_google_code, decode_google_id_token, create_jwt_pair, google_login.
- [2단계] app/api/v1/auth.py — POST /v1/auth/google. config·.env.example에 JWT_SECRET, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, ALLOWED_ORIGINS 추가.
- [2단계] docs/DEPLOYMENT.md — OAuth 핸드쉐이크(응답 body JSON) 확정 및 문서화.
- [2단계] requirements.txt — pyjwt, httpx 추가. 2단계 마일스톤 달성.
- [2단계] README.md — 로컬 실행 안내(uvicorn, alembic upgrade head), /health·/v1/auth/google 엔드포인트 설명.
- [2단계·디버그] Alembic 마이그레이션 UnicodeDecodeError·연결 실패 원인 규명 — psycopg2가 오류를 마스킹함. psycopg3 전환, creator로 포트 확실 적용. 실제 원인: 시스템 DATABASE_URL이 .env를 덮어씀. env.py psycopg3+creator, DEPLOYMENT에 DATABASE_URL 우선순위·DB 생성 안내 추가.
- [2단계·정리] Railway DB(DATABASE_PUBLIC_URL)로 마이그레이션 성공. alembic/env.py 디버그 로그 제거.
- [2단계·로컬 실행] ModuleNotFoundError(httpx, pyjwt) — pip install -r requirements.txt. Windows+asyncpg/psycopg 이슈 — run.py 추가(이벤트 루프 정책 선설정), database.py에서 postgresql+psycopg 사용. README 갱신.
- [2단계·배포] nixpacks.toml 추가 — 배포 시 `alembic upgrade head` 자동 실행 후 uvicorn 시작. DEPLOYMENT.md 빌드 설정에 반영.
- [2단계·배포] requirements.txt에 greenlet 추가 — Railway에서 "No module named 'greenlet'" 원인. SQLAlchemy AsyncSession에 greenlet 필수.
- [2단계·설정] JWT 만료 시간 환경변수화 — config.py에 jwt_access_expire_seconds, jwt_refresh_expire_days 추가. auth_service.py 하드코딩 제거. .env.example·DEPLOYMENT 갱신.
- [2단계·설정] DB 연결 검증 재시도 — verify_db_connection()에 retry 로직 추가. db_connect_retries(기본 5), db_connect_retry_interval_sec(기본 2) 설정 가능. Railway 컨테이너 환경 대비.
- [2단계·정리] DB·예외·패키지 4가지 수정 — (1) database.py _to_async_url 제거, asyncpg 직접 사용. run.py 이벤트 루프 정책으로 Windows 이슈 해결. (2) alembic/versions/002_fix_timestamp_nullable.py 추가, created_at·updated_at nullable=False. (3) main.py RequestValidationError 핸들러 추가, 422 마스킹 해결. (4) requirements.txt psycopg2-binary 제거.
- [로드맵·스키마] 4가지 개선점 반영 — (1) content_hash·is_manual_edited Notice 모델·003 마이그레이션 추가. (2) ROADMAP 2단계 본문 해시·수동 수정 플래그 설계, 3단계 content_hash 기반 변경 감지, 4단계 해시 변화 시에만 AI 재추출·is_manual_edited 덮어쓰기 방지, 5단계 FTS·GIN 인덱스, 추가 검토 API Rate Limit(slowapi).
- [보안·인프라] main.py — lifespan에 engine.dispose() 추가(커넥션 풀 종료), Exception 핸들러에서 asyncio.CancelledError 필터(re-raise로 정상 연결 종료 시 500 로그 방지).
- [로드맵] 보안·Auth 3건 반영 — 2단계 구글 ID 토큰 서명 검증(베타 전 google-auth), 추가 검토 토큰 무효화·로그아웃(Redis 블랙리스트·token_version), 5단계 GET /v1/users/me(프로필 매칭·설정 UI 필수).
- [테스트·CI] pytest·mypy·Ruff·GitHub Actions 도입 — requirements-dev에 mypy·pytest-asyncio, pyproject.toml(pytest·ruff·mypy 설정), tests/conftest·test_health, .github/workflows/ci.yml. Push/PR 시 Ruff→Mypy→Pytest 자동 실행. 1단계 검증(변동 대비) 완료.
- [기술 부채 Phase A] 3단계 전 수정 — (1) get_db 오토 커밋 제거, google_login에 session.commit() 명시. (2) google-auth verify_oauth2_token으로 ID 토큰 서명 검증 적용. (3) tests/test_auth_service.py 추가(create_jwt_pair·decode_google_id_token 단위 테스트). ROADMAP Phase B(Repository DTO·테스트 확장·Observability) 추가 검토에 기록.
- [배포 수정] requirements.txt에 requests 추가 — google-auth의 `transport.requests`가 JWKS fetch 시 requests 패키지 필요. Railway 배포 시 ModuleNotFoundError 해결.
- [로드맵·모바일] 6단계에 반응형·모바일 우선·터치 친화적 UI·목록·이미지 로딩 전략·스켈레톤·네트워크 에러 안내·프로필 폼 모바일 대응·스크롤 복원 반영. 추가 검토에 PWA·웹 푸시·OG 태그·Web Share API·데이터 절약 모드·접근성(WCAG)·OAuth 모바일 플로우 검증 반영.
- [로드맵] docs/ROADMAP.md — 확정 사항(코드·문서 기준) 섹션·단계별 목표 기간 표 추가. 2단계 Raw/일정/OAuth 문구를 "확정" 표현으로 정리. 6단계 달력 UX 확정(한 화면 통합+시각적 구분+토글 필터, 탭 비권장) 반영. 추가 검토 아이디어에 단계별 기간 표 링크 보강.
- [로드맵·문서] ROADMAP에 "미리 결정 필요 (진입 전)" 섹션 추가. 3·4·5단계별 결정 권고 항목 표로 정리. CAUTIONS 중복 수집 문구를 확정 사항(URL 미사용)과 맞춤. 추가 검토 아이디어에 문서 정합성 점검 항목 추가.
- [문서] README.md 개선 — 현재 상태 한 줄, 기술 스택 표, 로컬 실행 전제(Python 3.10+, PostgreSQL, .env.example), 문서 표에 ROADMAP 확정 사항 안내, Swagger /docs 안내, 참고 섹션 정리.

---

## 템플릿 (새 날짜에 복사)

```markdown
## YYYY-MM-DD

- [단계] 무엇을 했는지 (어떤 파일/기능). 왜 또는 결과 한 줄.
```
