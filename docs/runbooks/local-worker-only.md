# 로컬에서만 Celery 워커 돌리기 (클라우드가 작업 가져가지 않게)

실제 서비스는 클라우드 Redis/워커를 쓰고, **임시로** 로컬에서 워커를 돌려보고 싶을 때 사용.

## 원인

로컬과 클라우드가 **같은 Redis**(같은 `REDIS_CELERY_URL`/`REDIS_URL`)를 쓰면, 같은 큐를 두 워커가 함께 소비해서 클라우드 워커가 먼저 작업을 가져갈 수 있다.

## 해결: 로컬 전용 Redis로 브로커 분리

Celery 브로커만 **로컬 Redis**로 두면, 로컬에서 넣은 작업은 로컬 워커만 처리한다. 클라우드 설정은 건드리지 않는다.

---

## 1. 로컬 Redis 띄우기

- 이미 6379에 Redis가 있으면 생략.
- 없으면 예:
  - **Docker**: `docker run -d -p 6379:6379 redis`
  - **Compose**: `docker compose up -d redis` (compose.yml에 redis 서비스 있는 경우)

---

## 2. 로컬 .env에서 Celery 브로커만 로컬로

로컬에서 쓰는 `.env`에 **임시로** 아래 한 줄 추가 또는 수정:

```bash
REDIS_CELERY_URL=redis://localhost:6379/1
```

- `REDIS_URL`은 그대로 클라우드 Redis를 둬도 된다. (트리거 락 등은 클라우드 Redis 사용.)
- API도 로컬에서 띄울 경우, 트리거 시 같은 .env를 쓰므로 작업이 로컬 Redis에 들어가고 로컬 워커만 처리한다.

---

## 3. 로컬 워커 실행

프로젝트 루트에서:

```bash
set APP_ENTRY=celery
celery -A app.core.celery_app:app worker -l info -O fair --pool=solo -Q critical,crawl,ingestion,ai
```

- Windows: `--pool=solo` 필수. (DEPLOYMENT.md / README 참고.)
- Linux/Mac: `--pool=solo` 생략 가능.

---

## 4. (선택) 로컬 API로 트리거

로컬에서 API도 띄운 뒤, 같은 .env로 트리거하면 작업이 로컬 Redis → 로컬 워커로만 간다.

```bash
# 터미널 1: API
uvicorn app.main:app --reload

# 터미널 2: 워커 (위 3번)
# 터미널 3: 트리거 예시
curl -X POST "http://localhost:8000/internal/trigger-crawl?college_code=chemistry" -H "X-Crawl-Trigger-Secret: YOUR_SECRET"
```

---

## 5. 테스트 끝난 뒤 (원상 복구)

로컬에서만 쓰던 **임시** 설정이므로, 다시 클라우드와 맞추고 싶으면:

- `.env`에서 `REDIS_CELERY_URL=redis://localhost:6379/1` 줄을 **삭제**하거나 **주석 처리**하면, 다음부터는 `REDIS_URL`(또는 배포용 REDIS_CELERY_URL)을 쓰게 되어 클라우드 워커가 다시 작업을 가져간다.

클라우드 쪽 Variables는 수정하지 않아도 된다.
