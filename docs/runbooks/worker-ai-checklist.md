# Worker + AI 실행 체크리스트

Celery 워커와 AI 파이프라인을 수동 실행/검증할 때 매번 확인할 항목을 정리한다.

---

## 0) 실행 전 공통 체크

- [ ] `.env`에 `APP_ENTRY`, `DATABASE_URL`, `REDIS_URL`(또는 `REDIS_CELERY_URL`)이 설정되어 있다.
- [ ] `.env`에 `AI_PIPELINE_ENABLED=true`가 설정되어 있다.
- [ ] `.env`에 `GEMINI_API_KEY`와 `GEMINI_MODEL`이 설정되어 있다.
- [ ] DB 마이그레이션이 최신(head)이다.
  - `alembic current`
  - 필요 시 `alembic upgrade head`
- [ ] 워커가 읽는 DB에 `notice_taxonomy_mappings` 테이블이 존재한다.
- [ ] 중복 워커 방지를 위해 기존 Celery 프로세스를 정리했다.

---

## 1) 로컬 전용 워커 실행 (디버깅)

`docs/runbooks/local-worker-only.md`를 함께 참고한다.

- [ ] 로컬 Redis 준비 (`redis://localhost:6379/1`).
- [ ] `.env`에 `REDIS_CELERY_URL=redis://localhost:6379/1` 설정.
- [ ] Windows라면 아래 명령으로 워커 실행:

```powershell
$env:APP_ENTRY="celery"
celery -A app.core.celery_app:app worker -l info -O fair --pool=solo -Q critical,crawl,ai
```

- [ ] 로그에서 큐 `critical,crawl,ai` 소비 중인지 확인.
- [ ] 로그에서 model 초기화가 기대값(`GEMINI_MODEL`)인지 확인.

---

## 2) AI 태스크 재처리 체크

- [ ] `ai_status='pending'` 전환은 **이미 크롤링되어 DB에 저장된 기존 공지를 재처리할 때만** 사용한다.
  - 신규 크롤링으로 들어온 공지는 `AI_PIPELINE_ENABLED=true`일 때 파이프라인에서 자동으로 AI 큐에 들어가므로 수동 `pending` 전환이 필요 없다.
- [ ] 대상 notice를 `ai_status='pending'`으로 되돌렸다.
- [ ] `process_notice_ai_task`를 큐에 재등록했다.
- [ ] 워커 로그에서 아래를 확인했다:
  - [ ] `process_notice_ai_task ... received`
  - [ ] `ai_extraction_completed`
  - [ ] `Task ... succeeded`

---

## 3) 실패 원인 빠른 판별

### A. Gemini 404 (모델 미지원)

- 증상: `models/... is not found for API version v1beta`
- 조치:
  - [ ] 현재 API key에서 지원되는 모델 목록 확인
  - [ ] `.env`의 `GEMINI_MODEL`을 지원 모델로 변경
  - [ ] 워커 재시작 후 재시도

### B. Gemini 429 (쿼터/요금제)

- 증상: `RESOURCE_EXHAUSTED`, `quota exceeded`
- 조치:
  - [ ] Google AI Studio/Cloud에서 결제·쿼터 상태 확인
  - [ ] 필요 시 쿼터 상향 또는 키 교체
  - [ ] 반영 후 워커 재시작

### C. DB 스키마 불일치

- 증상: `relation "notice_taxonomy_mappings" does not exist`
- 조치:
  - [ ] 워커가 연결하는 DB 기준으로 `alembic upgrade head` 재실행
  - [ ] `alembic current` 재확인
  - [ ] 테이블 존재 여부 재확인 후 워커 재시작

### D. Alembic 상태 불일치(업그레이드 로그와 current가 다름)

- 증상: `alembic upgrade head` 로그에는 upgrade가 보이는데 `alembic current`가 이전 revision에 머무름
- 점검:
  - [ ] 워커/CLI가 같은 `DATABASE_URL`을 보는지 확인
  - [ ] 워커 연결 DB에서 `notice_taxonomy_mappings` 실제 존재 여부 확인
- 응급 복구(로컬/디버그 전용):
  - [ ] `NoticeTaxonomyMapping.__table__.create(bind=..., checkfirst=True)`로 테이블을 보장
  - [ ] 워커 재시작 후 AI 태스크 재처리
- 주의:
  - [ ] 이 방법은 임시 복구이며, 이후 원인(DB URL/마이그레이션 경로)을 반드시 정리한다
  - [ ] `create(checkfirst=True)`는 **테이블 생성만** 보장한다. 마이그레이션 `010_notice_taxonomy`에 포함된 백필·인덱스·`notices` 컬럼 변경 등은 적용되지 않으므로, 정상 경로는 여전히 `alembic upgrade head`로 맞춘다.

---

## 4) 미리보기 검증

- [ ] API 서버 실행 (`python run.py` 권장, Windows event loop 이슈 회피).
- [ ] 공개 검수 URL 확인:
  - `http://127.0.0.1:8000/internal/public-preview/engineering?limit=10`
- [ ] 다음 항목이 비어 있지 않은지 확인:
  - `지원자격`, `날짜`, `대분류`, `소분류`
- [ ] `본문(요약)`은 현재 검수 페이지에서 제거되어 `원문`/`본문 URL`로 확인한다.

---

## 5) 종료/원복

- [ ] 로컬 전용 설정(`REDIS_CELERY_URL=redis://localhost:6379/1`)을 계속 쓸지 결정했다.
- [ ] 임시 디버그 목적이었다면 `.env` 값을 원래 운영 기준으로 복원했다.
- [ ] 실행 결과를 `docs/WORK_LOG.md`에 1줄 기록했다.

