# AI 추출 스키마 설계 (NoticeAIExtraction) — 개선안 반영

**목적**: 4단계 Instructor + Gemini 출력 스키마를 "학생–공지 매칭" 목표에 맞게 견고하게 설계.  
**관련**: [ROADMAP_PHASES 4·5단계](../ROADMAP_PHASES.md), [database-spec notice_schedules](database-spec.md), [Instructor 적용 계획](.cursor/plans 참고).

---

## 1. 개선 제안 4가지 판단 요약

| # | 제안 | 판단 | 근거 |
|---|------|------|------|
| 1 | `target_grades` / `target_departments` 타입 엄격화 | **반영** | ROADMAP_PHASES "학과·학년 값 형식 통일, User 프로필과 비교 가능하도록" 명시. list[str]이면 AI가 "1학년"/"1"/"3+"/ "컴공" 등 제각각 출력해 5단계 매칭 로직이 깨짐. |
| 2 | Timezone + Fuzzy Date 대비 `date_raw` Fallback | **반영** | DB notice_schedules에 이미 `schedule_text_fallback`(VARCHAR 255) 존재. 파싱 불가("11월 중순", "추후 공지") 시 AI 환각/파싱 에러 방지용 원문 보존 필요. |
| 3 | 공지 카테고리 플래그 `NoticeCategory` | **반영(정책 변경)** | **대분류·소분류는 AI가 추출.** NoticeAIExtraction에 `category`(Enum), `sub_category`(str \| None, 최대 64자) 포함. DB notices.category / notices.sub_category에 투영. |
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
  - `notices.category` ← NoticeAIExtraction.category (Enum value 문자열), `notices.sub_category` ← NoticeAIExtraction.sub_category.

---

## 4. 계획 문서와의 연동

- "Instructor 기반 4단계 AI 파이프라인" 계획의 **스키마 설계** 섹션은 본 문서(ai-extraction-schema.md)를 SSOT로 참조한다.  
- `app/schemas/ai.py` 구현 시 위 Enum·필드·validator를 반영한다.
