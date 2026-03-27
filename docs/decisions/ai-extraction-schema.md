# AI 추출 스키마 설계 (NoticeAIExtraction) — 개선안 반영

**목적**: 4단계 Instructor + Gemini 출력 스키마를 "학생–공지 매칭" 목표에 맞게 견고하게 설계.  
**관련**: [ROADMAP_PHASES 4·5단계](../ROADMAP_PHASES.md), [database-spec notice_schedules](database-spec.md), [Instructor 적용 계획](.cursor/plans 참고).

---

## 1. 개선 제안 4가지 판단 요약

| # | 제안 | 판단 | 근거 |
|---|------|------|------|
| 1 | `target_grades` / `target_departments` 타입 엄격화 | **반영** | ROADMAP_PHASES "학과·학년 값 형식 통일, User 프로필과 비교 가능하도록" 명시. list[str]이면 AI가 "1학년"/"1"/"3+"/ "컴공" 등 제각각 출력해 5단계 매칭 로직이 깨짐. |
| 2 | Timezone + Fuzzy Date 대비 `date_raw` Fallback | **반영** | DB notice_schedules에 이미 `schedule_text_fallback`(VARCHAR 255) 존재. 파싱 불가("11월 중순", "추후 공지") 시 AI 환각/파싱 에러 방지용 원문 보존 필요. |
| 3 | 공지 카테고리 플래그 `NoticeCategory` | **반영(정책 변경)** | **대분류·소분류는 AI가 추출.** NoticeAIExtraction에 `category`(Enum), `sub_category`(str \| None, 최대 64자) 포함. 단, DB 영속은 `notice_taxonomy_mappings`(행 단위 매핑)으로 저장하고 단일 대표 컬럼(`notices.category/sub_category`)은 사용하지 않는다. |
| 4 | `is_all_day`일 때 시간 00:00:00 강제 | **반영** | DB와 프론트 일관성. model_validator로 스키마 단에서 강제하면 AI 모순 출력을 사전 차단. |

---

## 2. 반영된 스키마 구조 (개념)

### 2.1 Enum 정의

- **ScheduleKind**  
  - 기존 유지 (APPLICATION_DEADLINE, INTERVIEW, RESULT, EVENT, OTHER)
- **TargetGrade** (학년)  
  - `"1"`~`"6"`, `all`, `grad_master`, `grad_phd`, `grad_all`, `other`. 대학원·특수학제 반영.
  - "3+"는 `"3"` + 매칭 시 "3 이상" 해석으로 처리.
- **TargetDepartment**  
  - 학교 실제 학과 코드/명칭 목록을 Enum으로 두거나,  
  - 초기에는 `list[str]` 유지하되 **프롬프트에 "정규화된 학과 코드만 출력"** 강제 + 추후 Enum으로 전환.
- **NoticeCategory** (대분류)  
  - AI가 공지 본문을 보고 분류. 값: `scholarship`, `employment`, `event`, `academic`, `admission`, `international`, `other`.  
  - 소분류(`sub_category`)는 대분류 하위의 짧은 라벨(str, 최대 64자). 예: 장학 → "국가장학금", 취업 → "인턴 모집".

### 2.2 ScheduleItem

- **date_raw / start_date_raw / end_date_raw: str | None**  
  - **비대칭 날짜 처리**: 시작일·종료일을 독립 평가. 한쪽만 명확하면 명확한 쪽은 ISO8601로 채우고, 모호한 쪽만 null + 해당 \*_date_raw에 원문 보존 (예: "2026.02.01 ~ 채용 시 마감" → starts_at 채움, ends_at=null, end_date_raw="채용 시 마감").  
  - date_raw: 파싱 불가/애매한 날짜 원문 ("11월 중순", "추후 공지" 등).  
  - DB `notice_schedules.schedule_text_fallback` 등과 매핑.
- **model_validator**  
  - `is_all_day is True`이면 `starts_at`/`ends_at`의 시간(time) 부분을 00:00:00으로 정규화 (KST 기준 권장, 문서에 명시).

### 2.3 NoticeAIExtraction

- **category** (대분류): `NoticeCategory` Enum. AI가 본문 기준으로 하나만 선택. 분류 불가 시 `other`.
- **sub_category** (소분류): `str | None`, 최대 64자. 대분류에 맞는 짧은 라벨(예: "국가장학금", "인턴 모집"). 없으면 null.
- **schedules**  
  - 각 항목에 `date_raw`, `label` 포함.  
  - 타임존: "한국 공지이므로 KST(Asia/Seoul) 기준으로 해석"을 프롬프트 및 스키마 설명에 명시.

#### 2.3.1 Schema-driven Chain of Thought (자격 요건 — 환각 방지)

LLM이 JSON을 **위에서부터 순서대로** 생성한다는 점을 이용해, **엄격한 필드에 답하기 전에 원문 발췌 필드를 먼저 두는** 구조를 쓴다.

| 순서 | 필드 | 역할 |
|------|------|------|
| 1 | **raw_eligibility_text** | 본문에서 지원 자격 관련 문장을 **판단/가공 없이 그대로** 발췌. 없으면 null. (AI의 "도화지") |
| 2 | eligibility_rules | 위 원문을 바탕으로 분절한 자격 조건 리스트. |
| 3 | target_departments | 위 자격 요건에 명시된 학과 리스트. |
| 4 | target_grades | 위 자격 요건에 명시된 학년 리스트 (Enum). |

이 순서를 지키면, 모델이 `target_grades` 등 엄격한 포맷을 채울 때 **직전에 써 둔 원문(근거)**을 보고 채우게 되어 환각을 줄일 수 있다.

- **target_grades**: `list[TargetGrade]` 제한 (1~6, all, grad_master, grad_phd, grad_all, other).
- **target_departments**: `list[str]` + 프롬프트 정규화. 플레이스홀더("없음","알 수 없음") 금지.

#### 2.3.2 자격 요건 추출 정책 (제한 조건 기반)

- **엄격한 제한 조건이 문단에 있을 때만** raw_eligibility_text·eligibility_rules·target_* 를 채운다: 학년/학과/학점 커트라인, 지원·참석·수혜 자격을 판가름하는 조건.
- **"안내를 받아야 하는 대상"만 있고 판별 조건이 없으면** 추출하지 않는다: raw_eligibility_text=null, eligibility_rules=[], target_departments=[], target_grades=[].

---

## 3. 구현 시 유의사항

- **Pydantic v2**: `model_validator(mode="after")` 사용.  
- **Instructor**: Enum/Literal은 Gemini 제한(문자열 반환) 있으므로, 필요 시 후처리에서 문자열→Enum 변환 허용.  
- **DB 매핑**:  
  - `notice_schedules.schedule_text_fallback` ← `ScheduleItem.date_raw` / start_date_raw / end_date_raw  
  - `notice_taxonomy_mappings(main_category, sub_category)` ← `NoticeAIExtraction.taxonomy_mappings`를 행 단위로 평탄화해 저장.

---

## 4. 계획 문서와의 연동

- "Instructor 기반 4단계 AI 파이프라인" 계획의 **스키마 설계** 섹션은 본 문서(ai-extraction-schema.md)를 SSOT로 참조한다.  
- `app/schemas/ai.py` 구현 시 위 Enum·필드·validator를 반영한다.

---

## 5. 관측성 및 메타 저장 정책

### 5.1 DB에 영속 저장되는 내용

- `notices.ai_extracted_json` 컬럼에는 **NoticeAIExtraction 전체 JSON** 이 그대로 저장된다.
  - 비즈니스 필드: `category`, `sub_category`, `schedules`, `raw_eligibility_text`, `eligibility_rules`, `target_departments`, `target_grades`, `hashtags`, `pipeline_version` 등.
  - 메타데이터 필드: `metadata` 딕셔너리 내부에 `_envelope_meta` 네임스페이스를 둔다.
- `_envelope_meta`는 **AI 실행 단위 운영 메타**를 포함하며, 구조는 다음과 같다.
  - `pipeline_version`: 파이프라인/프롬프트 버전 (NoticeAIExtraction.pipeline_version와 동일 값).
  - `provider`: `"google/{model}"` 형식의 프로바이더 식별자.
  - `model`: Gemini 모델 이름(예: `gemini-1.5-flash`).
  - `fallback_reason`: `None` 또는 `"validation_error"`, `"validation_retry_exhausted"`, `"provider_error"` 등 고정 문자열.
  - `html_raw_len`: 전처리 전 HTML 길이(문자 수).
  - `html_clean_len`: 전처리 후 프롬프트로 사용된 slim_html 길이(문자 수). (키 이름은 하위 호환을 위해 유지)
  - `image_count`: 멀티모달 입력에 사용된 이미지 개수.
  - `elapsed_ms`: `extract_notice_info` 기준 end-to-end 처리 시간(ms).
  - `usage`: 토큰 사용량 딕셔너리  
    - `prompt_tokens`: 입력(prompt) 토큰 수(집계용).  
    - `completion_tokens`: 출력(completion) 토큰 수(집계용).  
    - `total_tokens`: `prompt_tokens + completion_tokens`.  
- **테스트 계약**  
  - `tests/test_ai_pipeline_schema.py::test_project_extraction_to_notice_fields_includes_envelope_meta` 에서 `_envelope_meta`가 `metadata` 안에 네임스페이스로만 저장되고, 위 키들이 round-trip 가능한 shape으로 유지되는지 검증한다.
  - `tests/test_ai_pipeline_schema.py::test_ai_extracted_json_round_trips_through_notice_ai_extraction` 에서 DB에 저장된 `ai_extracted_json`이 `DomainNoticeAIExtraction.model_validate()`로 항상 복원 가능해야 함을 고정한다 (extra=\"forbid\" 유지).

### 5.2 로그·메트릭으로만 남기는 내용 (운영 SSOT)

- **집계·모니터링용 SSOT는 메트릭/로그** 로 두고, DB는 개별 notice 단위 디버깅/리플레이 목적에 한정한다.
- 메트릭 레이어(`app/core/metrics.py` 및 관련 테스트)에서는 다음을 집계한다.
  - 추출 시도/성공/폴백/프로바이더 오류 카운트 (예: `ai_extraction_attempt_total`, `ai_extraction_success_total` 등).
  - 토큰 사용량 총합 (`ai_extraction_tokens_total` 등, `usage.total_tokens` 기준).
  - 라벨 카디널리티는 `provider`, `model`, `status`, `reason` 등 **고정 enum 값**만 허용하며, `notice_id` 등 high-cardinality 값은 절대 사용하지 않는다.
  - 5~6단계 매칭·알림 전 단계 훅: `notice_ai_extraction_completed_total`(라벨 `college_code`는 `colleges.external_id`만), 구조화 로그 `notice_ai_extraction_completed`, Redis 리스트 `dicee:ai_extraction_completed_queue`(스텁; Redis 오류 시에도 AI 태스크 본처리는 성공 유지).
- 구조화 로그(예: `"ai_extraction_completed"`)는 `_envelope_meta`의 서브셋만 포함하며, 개별 notice 단위 분석/디버깅을 보조한다.

### 5.3 설계 원칙 요약

- **비즈니스 payload** (`NoticeAIExtraction`의 도메인 필드)는 DB SSOT로서 항상 round-trip 가능해야 한다.
- **운영 메타** (`_envelope_meta`)는
  - per-notice 수준에선 DB `metadata._envelope_meta`에 보존해 디버깅과 회귀 분석에 활용하고,
  - 집계/알람/대시보드 수준에선 메트릭·로그만을 SSOT로 사용한다.
- `_envelope_meta`의 필드가 추가/변경되더라도
  - `metadata` 네임스페이스 안에만 위치해야 하며,
  - 도메인 스키마(extra=\"forbid\")를 깨지 않도록 테스트를 통해 회귀를 방지한다.

### 5.4 raw substring 검증과 멀티모달

- **ai_extraction_enforce_raw_substrings** 가 True여도, **image_urls가 비어 있지 않으면** raw substring 검증을 수행하지 않는다.
- 이유: 모델은 이미지(포스터·첨부)까지 참고해 일정/자격을 추출하므로, 이미지에만 있는 문구는 HTML 본문(prompt_html)에 없을 수 있다. 이때 텍스트만 source로 검증하면 정상 추출이 거짓 fallback( raw_substring_validation_failed )으로 처리된다.
- 따라서 substring 검증은 **텍스트 전용 입력일 때만** 적용하며, 멀티모달 경로와 검증 규칙이 충돌하지 않도록 한다.

---

Quality Gates (2026-03-27): `pytest` full suite → 300 passed, 3 skipped (M2 마무리: AI 완료 훅·동기 DB 멱등·/ready last_crawl_success).
Quality Gates (2026-03-19): `pytest tests/test_ai_pipeline_schema.py tests/test_tasks_ai_consistency.py tests/test_ai_metrics.py tests/test_ai_html_cleaning.py tests/test_ai_extraction_domain.py` → 51 passed, 1 skipped.
Quality Gates (2026-03-19, slim_html): `pytest tests/test_ai_html_cleaning.py tests/test_ai_pipeline_schema.py tests/test_tasks_ai_consistency.py` → 37 passed, 1 skipped.
