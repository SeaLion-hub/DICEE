# 현재 작업 컨텍스트 (3단계 문서)

Composer(Cmd+I) 사용 시 **@todo.md**를 반드시 포함해 세션 컨텍스트를 유지하라. **매 프롬프트마다 [Current Session Context]를 상기**하면 AI가 30분마다 기억을 잃는 문제를 줄일 수 있다.

---

## [Current Session Context] — 단기 맥락 (매 턴 상기)

**지금 당장 풀고 있는 문제**를 명시적으로 고정한다. 백로그(할 일 목록)와 구분해, "현재의 상태"만 적고 대화가 이어질 때마다 갱신·참조하라.

| 항목 | 내용 |
|------|------|
| **현재 수정 중** | 없음 (버그 수정·마이그레이션·용량 상향 완료) |
| **발생 중인 이슈** | 없음 |
| **주의 사항** | 규칙·매뉴얼은 .cursor/rules/·docs/rules/ 참조, WORK_LOG에 실제 수정만 기록 |

- 위 세 칸을 비우지 말고, 작업이 바뀔 때마다 갱신하라. AI는 이 블록을 읽고 "지금 어떤 문제를 풀고 있었지?"를 복기한다.

---

## [Plan] — 계획서

작업 시작 전 또는 사용자 지시에 따라 여기에 **계획**을 적어 둔다. 새 크롤러·새 API·스키마 변경 시 관련 결정 문서를 참조해 작성한다.

- **예시(새 대학 크롤러)**: @docs/decisions/database-spec.md를 참고해 Notice 스키마·필수 필드(published_at, external_id, title, url 등)를 확인한 뒤, 베이스/기존 크롤러 패턴을 따라 단계별 계획을 적는다.
- 한 번에 "모든 크롤러 다 만들어줘"라고 하지 말고, **"베이스 클래스 상속 확인 → 로그인/세션 로직 → 파싱 로직"**처럼 끊어서 지시하고, 그때마다 이 [Plan]과 [Checklist]를 갱신하게 하라.

(최신) 3단계 마무리 및 안정화: 데이터 적재 상태 모니터링, 예외 상황(IP 차단 등) 대응 설계 검토.

---

## [Context] — 맥락 노트

**현재 진행 중인 파일·스키마·상태**를 요약해 둔다. 금붕어 기억력 문제를 줄이기 위해 수정할 때마다 갱신한다.

- **예시**: "진행 중: app/services/crawlers/yonsei_ai.py. Notice 모델의 published_at, external_id, title, url, raw_html 필수. content_hash는 제목+본문 텍스트만 사용."
- 현재 수정 중인 파일(@yonsei_ai.py 등)의 **[Context]**를 요약해 이 섹션에 적고, 다음 턴에서도 @todo.md를 참조하면 맥락을 잃지 않는다.

완료된 작업:
- `.env` 유효성 검사 에러 수정 (`APP_ENTRY`, `ENVIRONMENT`)
- `asyncpg`/`psycopg` 공통 DB 연결 로직 (`app/core/database.py`)
- `009_crawl_runs` 수동 마이그레이션 완료
- `MAX_HTML_BYTES` 10MB 상향 (`crawl_http.py`, `crawl_payload.py`)
- SSL 쿼리 정규화 (`app/core/database_sync.py`)

---

## [Checklist] — 체크리스트

수정할 때마다 **한 항목씩 지워나가며** 완료 보고를 한다. "다 했습니다"만 하지 말고, 어떤 항목을 끝냈는지 여기서 체크하고 보고하라.

- [x] 버그 수정: Settings 유효성 검사 에러 (APP_ENTRY)
- [x] 버그 수정: DB 연결 TypeError (options vs server_settings)
- [x] DB 마이그레이션: 009_crawl_runs 수동 적용
- [x] 기능 상향: MAX_HTML_BYTES 10MB로 증가
- [x] 기능 개선: 동기 DB SSL 쿼리 정규화
- [x] md 파일 uptodate 확인 및 최신화 (README·CAUTIONS·ROADMAP_PHASES·WORK_LOG·todo)

---

**사용 예시 (새 크롤러 추가 시)**  
1. "@docs/decisions/database-spec.md를 참고하여 [Plan]을 todo.md에 작성해."  
2. "현재 진행 중인 파일들(@yonsei_ai.py 등)의 [Context]를 요약해."  
3. 수정 후 "방금 한 변경으로 [Checklist]에서 완료된 항목을 체크하고, 다음 단계만 남겨."
