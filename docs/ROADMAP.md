# DICEE 개발 로드맵

**전략(Roadmap)** 전용 문서. 결정 상세는 [ADR](decisions/), 기록은 [WORK_LOG](WORK_LOG.md), 단계별 실행 상세는 [ROADMAP_PHASES](ROADMAP_PHASES.md) 참고.

---

## 목차

- [지금 상태](#지금-상태)
- [1. Engineering Principles (엔지니어링 원칙)](#1-engineering-principles-엔지니어링-원칙)
- [2. Strategic Milestones (전략적 마일스톤)](#2-strategic-milestones-전략적-마일스톤)
- [3. Technical Pillars (기술적 기둥)](#3-technical-pillars-기술적-기둥)
- [4. Success Metrics (성능 지표)](#4-success-metrics-성능-지표)
- [관련 문서](#관련-문서)

---

## 지금 상태

| 항목 | 내용 |
|------|------|
| **현재 마일스톤** | **M2 Intelligence** (크롤러·작업 큐 연동 및 AI 파이프라인 구축) |
| **배포** | 백엔드 Railway, 프론트 Vercel. 상세 [DEPLOYMENT](DEPLOYMENT.md). |
| **작업 기록** | [WORK_LOG](WORK_LOG.md) |
| **단계별 할 일·확정 사항·예상 문제** | [ROADMAP_PHASES](ROADMAP_PHASES.md) |
| **코딩 시 주의** | [CAUTIONS](CAUTIONS.md) |

---

## 1. Engineering Principles (엔지니어링 원칙)

이 프로젝트가 타협하지 않는 기술적 가치. **이 원칙에 어긋나는 기능은 개발 순위에서 밀려난다.**

| 원칙 | 요약 |
|------|------|
| **Async-First** | FastAPI·DB는 비동기(AsyncSession, asyncpg). Celery 워커는 동기(psycopg2) 전용. 라우터는 `async def`·비동기 클라이언트 사용. |
| **Zero-Downtime Crawling** | IP 차단·429·OOM을 **예상 문제**가 아닌 **핵심 설계 요건**으로 취급. Polite crawling, rate limit, 지수 백오프, 모니터링 필수. |
| **Strict Security & Auth** | OAuth·JWT 설계 일원화. 토큰 갱신·검증·Blocklist 정책 명시. 시크릿은 환경변수·SecretStr, 비교는 constant-time. |
| **관심사 분리** | Router → Service → Repository. 결정은 ADR, 기록은 WORK_LOG. 로드맵은 전략·마일스톤·기둥·지표만 유지. |

---

## 2. Strategic Milestones (전략적 마일스톤)

단계를 **기능적 가치** 중심으로 재편. 상세 할 일·검증은 [ROADMAP_PHASES](ROADMAP_PHASES.md).

| 마일스톤 | 범위 | 목표 |
|----------|------|------|
| **M1: Foundation** | 인프라·인증 | 비동기 백엔드 뼈대, PostgreSQL·ORM, Railway 배포, 구글 OAuth·JWT·User 스키마 확립. |
| **M2: Intelligence** | 수집·AI | 연세대 크롤러(레포 이식)·Celery·Redis 연동, Multimodal AI 파이프라인(Gemini), 자격요건·일정 추출·저장. |
| **M3: Engagement** | 매칭·프론트 | 검색·프로필 매칭 API, 일정·달력 API, Next.js 프론트 연동, 반응형·모바일 우선, 런칭. |

---

## 3. Technical Pillars (기술적 기둥)

프로젝트 생존을 좌우하는 **핵심 인프라·운영 요건**. 상세 대비표는 [ROADMAP_PHASES](ROADMAP_PHASES.md) 및 [CAUTIONS](CAUTIONS.md).

| 기둥 | 핵심 요건 |
|------|-----------|
| **Scalability · 크롤 안정성** | **대학 WAF·IP 차단**: Polite crawling(요청 간 1초, 단과대별 5분 stagger), 크롤 주기 6시간. 데이터센터 IP·User-Agent 대응: Chrome UA 사용. Timeout·403 다발 시 **프록시 로테이션**(ScraperAPI, ZenRows 등) 검토. |
| **Reliability · AI·워커** | **429 대응**: Gemini 호출 `rate_limit='10/m'`, 지수 백오프 재시도, max_retries 후 DLQ. **OOM 방지**: Playwright는 JS 필수 시에만, `--no-sandbox`·`--disable-dev-shm-usage`, concurrency 1~2. Celery payload는 notice_id만, 대용량은 DB에서 조회. |
| **Search · 검색** | 베타: PostgreSQL FTS(tsvector)·GIN 인덱스. 트래픽 증가 시 Vector Search(RAG 대비) 전환 로드맵. |
| **Reliability · 모니터링** | Sentry(백엔드·워커) 필수. 추후 Sentry·Prometheus 통합 모니터링 대시보드 구축. |
| **Security · Auth** | OAuth 핸드쉐이크·토큰 갱신을 한 곳에서 설계. [ADR](decisions/) 및 [ROADMAP_PHASES](ROADMAP_PHASES.md) 확정 사항 참고. |

---

## 4. Success Metrics (성능 지표)

단순 "기능 완성"이 아니라 **수치로 검증 가능한 지표**.

| 지표 | 목표 |
|------|------|
| **Crawl Success Rate** | 99.5% 이상 유지 (IP 차단·타임아웃·파싱 실패 최소화). |
| **API P99 Latency** | 100ms 미만 (목록·검색·달력 API). |
| **AI Extraction Accuracy** | 90% 이상 (수동 수정 비율 10% 미만). 피드백 루프("나와 관련 없는 공지")로 지속 개선. |
| **Uptime · 장애 감지** | Sentry·헬스체크 기반 조기 감지. 크롤 0건·연속 실패 시 알람. |

---

## 관련 문서

| 문서 | 용도 |
|------|------|
| [ROADMAP_PHASES](ROADMAP_PHASES.md) | 단계별 할 일·확정 사항·미리 결정 필요·예상 문제·대비·추가 검토 아이디어·기술 부채 반영 계획. |
| [WORK_LOG](WORK_LOG.md) | 실제로 한 수정의 기록. 로드맵 본문 변경 시 여기에만 이력 기록. |
| [CAUTIONS](CAUTIONS.md) | 코딩 전·중 체크리스트 (구조, 시크릿, 크롤러, AI, Auth, 배포). |
| [DEPLOYMENT](DEPLOYMENT.md) | Railway·Vercel·환경변수·빌드·Redis·DB. |
| [decisions/](decisions/) | ADR (Architecture Decision Record). 예: [001 Notice 일정 스키마](decisions/001-notice-schedule-schema.md). |

---

**작성 규칙**

- 로드맵 본문 수정 시 **날짜·수정 내용·이유는 WORK_LOG에만 기록**.
- 새 기능·변경 아이디어는 ROADMAP_PHASES의 "추가 검토 아이디어"에만 적고, 마일스톤 완료 시 사용자에게 검토 여부 확인.
