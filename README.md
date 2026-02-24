# DICEE

대학교 공지사항의 **분산과 이용자의 번거로움**을 줄이기 위한 서비스.

---

## 목차

- [아이디어와 맥락](#아이디어와-맥락)
- [기술 스택](#기술-스택)
- [문서](#문서)
- [로컬 실행](#로컬-실행)
- [주요 엔드포인트](#주요-엔드포인트)
- [참고](#참고)

---

## 아이디어와 맥락

### 문제

- 대학 공지는 **학과·단과대·중앙** 사이트에 흩어져 있음.
- 장학·취업·점검 등 **종류가 다양**해, 학생이 매번 여러 곳을 돌아다니며 확인하기 번거로움.

### 목표

- **한곳에서** 공지를 모아 보고,
- **내 조건**(전공·학년·군필·학점 등)에 맞는 공지만 골라 보여 주는 경험 제공.

### MVP (첫 번째 버전)

- [SeaLion-hub/DICE (test 브랜치)](https://github.com/SeaLion-hub/DICE/tree/test)
- FastAPI + PostgreSQL + Redis + Apify + Gemini로 구현.
- 겪었던 구조적 문제: 동기 DB/블로킹 라우트, Raw SQL, 불안정한 AI 파싱, 단일 파일 과다 책임 등.

### 이 레포(DICEE-1)

- 위 MVP를 참고하되 **초석부터 다시 설계**한 재구축 프로젝트.
- 반영 사항: 비동기 백엔드, ORM, 계층형 구조, Playwright 자체 크롤러, Structured AI 출력, Auth(구글 OAuth + JWT, 다중 제공자 확장 가능), Celery rate limit 등.
- 배포: 백엔드 **Railway**, 프론트 **Vercel**.

**현재**: 3단계 진행 중 (연세대 크롤러 레포 이식·Celery·Redis·trigger-crawl). 단계·마일스톤·구현 현황은 [ROADMAP](docs/ROADMAP.md) 참고.

---

## 기술 스택

| 구분 | 내용 |
|------|------|
| **Backend** | FastAPI, SQLAlchemy 2.0(비동기), PostgreSQL, Redis, Celery |
| **Auth** | 구글 OAuth + JWT (다중 제공자 확장 가능) |
| **Crawler** | requests+BS4(레포 이식), Playwright 필요 시 |
| **AI** | Gemini Structured Output |
| **배포** | 백엔드 Railway, 프론트 Vercel(6단계에서 Next.js) |

---

## 문서

| 문서 | 설명 |
|------|------|
| [docs/ROADMAP.md](docs/ROADMAP.md) | 1~6단계 로드맵, 현재 단계·마일스톤. **확정 사항**(데이터 구조·OAuth·달력 UX 등)은 동 문서 상단 표 참고. |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Railway(백엔드)·Vercel(프론트) 배포 설정 |
| [docs/WORK_LOG.md](docs/WORK_LOG.md) | 작업별 구체적 수정 기록 |
| [docs/CAUTIONS.md](docs/CAUTIONS.md) | 바이브 코딩 시 주의사항·체크리스트 |

---

## 로컬 실행

**필요 환경**: Python 3.10+, PostgreSQL, (3단계 이후) Redis. `.env`는 [.env.example](.env.example)을 복사한 뒤 값을 채우고, 변수 목록·배포 시 설정은 [DEPLOYMENT](docs/DEPLOYMENT.md) 참고.

```bash
# 가상환경 생성·활성화 후
pip install -r requirements.txt
# .env 설정 후 DB 마이그레이션 (로컬 PostgreSQL 또는 Railway DB)
alembic upgrade head

# Windows: python run.py (이벤트 루프 정책·psycopg 호환)
# Linux/Mac: uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
python run.py
```

- **DATABASE_URL**: 시스템 환경변수가 .env를 덮어씀. Railway DB만 쓰려면 `$env:DATABASE_URL = $null`(PowerShell) 후 실행.

**3단계: Celery 워커 (로컬)**

- Redis 실행 후 별도 터미널에서 워커 기동.
- **Windows**: prefork 풀 미지원이므로 **`--pool=solo`** 필수.  
  `celery -A app.worker worker -l info --pool=solo`
- Linux/Mac: `celery -A app.worker worker -l info`
- trigger-crawl 테스트 시 Windows PowerShell에서는 `curl`이 별칭이므로 **`curl.exe`** 사용 권장.  
  예: `curl.exe -X POST "http://localhost:8000/internal/trigger-crawl?college_code=engineering" -H "X-Crawl-Trigger-Secret: YOUR_SECRET"`

---

## 주요 엔드포인트

- `GET /health`: 헬스 체크
- `POST /v1/auth/google`: 구글 OAuth code로 JWT 발급  
  필요 환경변수: `DATABASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `JWT_SECRET`

API 전체 목록·스키마는 실행 후 **Swagger UI** (`/docs`)에서 확인.

---

## 참고

- 이 레포는 위 목표를 위한 **재구축 프로젝트**이며, 첫 번째 버전(MVP) 코드는 [SeaLion-hub/DICE @ test](https://github.com/SeaLion-hub/DICE/tree/test)를 참고함.
