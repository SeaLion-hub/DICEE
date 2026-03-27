# User–Notice 매칭 규칙 및 5단계 API 계약

**상태**: APPROVED (정책 확정, 구현은 별도 PR·테스트로 검증)  
**작성·승인**: 2026-03-27 (탭 UX·학과 선택형·툼스톤 방향 당사자 확인 반영)  
**관련**: [ai-extraction-schema.md](ai-extraction-schema.md), [database-spec.md](database-spec.md), [ROADMAP_PHASES.md](../ROADMAP_PHASES.md)

---

## 1. 목적

5단계(검색·매칭·달력 API) 구현 전에 **사용자 프로필과 공지 AI 추출 필드의 비교 규칙**, **목록 페이지네이션**, **달력 조회 범위**, **크롤 기반 소프트 삭제**를 한곳에서 고정한다.

---

## 2. 사용자 프로필 저장 형식 (`users.profile_json`)

**현재 SSOT**: 애플리케이션은 `users.profile_json` (JSONB)만 존재한다. DB 명세서의 `user_profiles.matching_profile` 테이블이 도입되면 **동일 스키마를 이전**하는 것을 전제로 한다.

### 2.1 필드 (v1)

| 키 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `schema_version` | `int` | 권장 | 프로필 스키마 버전. 초기값 `1`. |
| `department_codes` | `list[str]` | 아니오 | **카탈로그에서만 선택**된 학과·단과대 식별자. 자유 입력 문자열 저장 금지. 허용 값 집합은 서버가 제공하는 목록과 동일해야 한다. |
| `grades` | `list[str]` | 아니오 | [TargetGrade](ai-extraction-schema.md)와 동일한 **문자열 값**만 허용. UI는 **체크박스·멀티 셀렉트** 등 선택형으로만 받는다 (자유 입력 금지). |
| `display_name` | `str` | 아니오 | UI 전용. 매칭에 사용하지 않는다. |

### 2.1-A 학과·학년 입력 방식 (확정)

- **학과**: 프리텍스트 입력이 아니라 **서버가 내려주는 옵션에서만** 고른다. 예: `GET /v1/meta/department-options` (이름은 구현 시 조정 가능) 또는 정적 시드와 동일한 키 집합. PATCH/PUT 시 **알 수 없는 코드는 422**.
- **학년**: `TargetGrade`에 대응하는 **고정 enum 목록**에서만 선택. 역시 자유 입력 금지.
- **이유**: AI `target_departments`와의 문자열 비교를 안정화하고, 오타·별칭 난립을 막는다.

### 2.2 카탈로그와 매칭용 라벨

- 각 `department_code`는 서버에 **정규화된 표시 라벨**(및 필요 시 동의어)과 매핑된다. v1 매칭은 공지 `target_departments` 문자열(정규화 후)과 유저가 고른 코드들의 **공식 라벨 집합**에 대한 **완전 일치**로 한다.
- AI가 카탈로그 밖 문자열을 내면 해당 축에서 매칭 실패로 끝날 수 있으므로, 추후 **동의어 테이블** 또는 프롬프트에 허용 라벨 힌트 주입을 검토한다 (열린 과제).

### 2.3 “프로필로 매칭 가능” 정의 (확정)

- **프로필 완성 (matching_eligible)**: `department_codes` 또는 `grades` 중 **하나라도** 비어 있지 않은 배열이면 true.
- **UI (6단계)**: **전체** 탭에서는 일반 목록·검색 API로 공지를 본다 (매칭 필터 없음). **맞춤**(개인 피드) 탭에서는 매칭 전용 API를 쓴다.
- `matching_eligible == false` 인 경우: **맞춤** API는 **200 + 빈 목록**과 메타 `requires_profile: true` (또는 동등 플래그). **전체** 탭은 그대로 이용 가능하다.

*(로드맵의 False Positive 지향은 “공지 쪽 제한이 애매할 때”에 적용. **맞춤** 탭만 프로필을 요구한다.)*

---

## 3. 공지 쪽 데이터 (AI 추출)

- `ai_extracted_json` 내 `target_departments`: `list[str]` ([ai-extraction-schema.md](ai-extraction-schema.md) 검증·플레이스홀더 금지).
- `target_grades`: `list[TargetGrade]` (DB JSON에는 문자열로 저장).
- **제한 없음(브로드캐스트)**: 해당 축에서 **빈 리스트**이면 “그 축에 대한 제한 없음”으로 해석한다.

---

## 4. 매칭 규칙 (v1)

### 4.1 두 축: 학과·학년

- **학과 축**: `target_departments`가 비어 있으면 **축 통과**. 비어 있지 않으면, 유저 `department_codes`에 대응하는 **공식 라벨**(§2.2)을 정규화한 집합과, 공지 쪽 문자열을 정규화한 항목 사이에 **완전 일치**가 **하나라도** 있으면 통과.
- **학년 축**: `target_grades`가 비어 있으면 **축 통과**. 비어 있지 않으면 아래 4.2에 따라 유저 `grades`와 교집합이 있으면 통과.

### 4.2 학년 교집합

- 공지에 `"all"` 또는 `"grad_all"`이 있으면 학년 축 **통과**.
- 그 외에는 공지의 각 값과 유저 `grades`를 집합으로 본다.
- 유저 목록에 `"3"`이 있고 공지에 `"4"`만 있으면 **불일치**.
- [ai-extraction-schema.md](ai-extraction-schema.md)의 **“3+는 3 이상 학년으로 해석”**은 **공지 텍스트가 그렇게 추출된 경우**에 한해, 구현에서 `"3"`을 `{"3","4","5","6"}` 확장으로 매핑할지 **후속 결정**. **초안 기본값**: AI가 `TargetGrade`에 맞게만내므로 **추가 확장 없이 리터럴 일치만** 적용한다.

### 4.3 최종 판정

- **학과 축 통과 AND 학년 축 통과**이면 해당 공지는 “이 유저에게 매칭됨”.
- `matching_eligible == false` 이면 위 판정을 하지 않고 2.3대로 빈 매칭 목록을 반환한다.

---

## 5. 공지 목록 API 페이지네이션

### 5.1 방식

- **커서 기반**을 기본으로 한다. 정렬 키는 DB partial 인덱스와 동일하게  
  `published_at DESC NULLS LAST`, 동률 시 `id DESC`.
- 커서는 **불투명 문자열**(예: base64url 인코딩된 `(published_at, id)` 또는 서명 토큰). 클라이언트는 파싱하지 않는다.

### 5.2 파라미터

| 파라미터 | 설명 |
| --- | --- |
| `limit` | 페이지 크기. **기본 20**, **최대 50**. |
| `cursor` | 이전 응답의 `next_cursor`. 첫 페이지는 생략. |

### 5.3 응답

- `items`, `next_cursor` (없으면 null), 선택적 `has_more`.

**이유**: 크롤 중간에 새 공지가 들어와도 offset 페이지네이션보다 건너뜀·중복이 적다.

---

## 6. 달력 API 조회 범위

### 6.1 엔드포인트 계약 (v1)

- `GET /v1/calendar/events` (ROADMAP 상 경로; 구현 시 `/v1` prefix 유지).

### 6.2 쿼리 모드 (둘 중 하나)

| 모드 | 파라미터 | 동작 |
| --- | --- | --- |
| **월 뷰** | `year`, `month` (정수, 1–12) | 해당 월의 `[month_start, next_month_start)` 와 `notice_schedules.start_at`·`end_at`이 겹치는 일정을 포함. |
| **구간 뷰** | `from`, `to` (ISO 8601 날짜 또는 datetimes, **반열린 구간** `[from, to)` 권장) | 주간·커스텀 범위. **양쪽 모두 필수**이며 `from < to`. |

- **동시 지정**: `from`/`to`가 있으면 **구간 모드 우선**, `year`/`month`는 무시하거나 400으로 거절한다. **초안 권장**: 구간 모드 우선, 월 파라미터 무시.

### 6.3 응답 (ROADMAP 정합)

- **두 배열**: (1) 매칭된 공지에서 파생한 일정 목록, (2) `user_calendar_events` 기반 사용자 고정 일정.
- ORM은 현재 `user_calendar_events`가 `notice_id` 단위(`app/models/user_calendar_event.py`)이므로, API는 공지·일정 조합을 **서비스에서 조립**한다.

---

## 7. 크롤 “툼스톤” (목록에서 사라진 공지)

### 7.1 추천안 (채택)

**`deleted_at` 소프트 삭제 툼스톤을 채택한다.** 당사자가 운영 경험이 없어 위임한 경우의 **추천 근거**는 다음과 같다.

- [database-spec.md](database-spec.md)에 이미 `notices.deleted_at`·partial index가 있어 **목록·유니크 인덱스와 같은 언어**로 다룰 수 있다.
- 하드 삭제보다 **복구(재크롤 시 upsert로 `deleted_at` 해제)**가 단순하다.
- “사라진 공지”를 사용자에게 숨기면서도 **감사·디버깅**을 위해 행을 남길 수 있다.

### 7.2 동작

- 단과대 **한 사이클 크롤이 성공적으로 완료**된 뒤, 이번에 수집한 `external_id` 집합에 **포함되지 않는** 해당 단과대 소속 기존 행에 `notices.deleted_at`을 설정한다.
- 이후 크롤에서 동일 `external_id`가 다시 나오면 upsert 시 **`deleted_at` 해제(복원)** 가능해야 한다.

### 7.3 안전장치

- **부분 실패·중단**된 런에서는 툼스톤을 수행하지 않는다 (오삭제 방지).
- 운영 **플래그**로 툼스톤 on/off (배포 직후·장애 시 끄기).
- 첫 출시 전 스테이징에서 **한 단과대·소량 데이터**로 한 번 검증한다.

---

## 8. 구현 순서 제안

1. **학과 카탈로그**: 시드 JSON 또는 DB 테이블 + `GET …/meta/department-options` (읽기 전용).
2. Pydantic 스키마: `UserProfileForMatching` (`department_codes`·`grades` 검증) + 정규화 유틸 + 단위 테스트.
3. `NoticeAIExtraction`에서 읽은 `target_*`와 비교하는 순수 함수 (`services` 레이어).
4. 목록·맞춤·달력 라우터는 기존 **Router → Service → Repository** 규칙 준수.

---

## 9. 열린 질문

- AI `target_departments`와 카탈로그 라벨 불일치 완화: **동의어 테이블** 또는 프롬프트에 허용 라벨 힌트.
- 퍼지 검색·초성 검색: [ROADMAP_PHASES SNUTT 벤치마킹](../ROADMAP_PHASES.md) 후속.
- 매칭 결과 **푸시 알림 큐**: 페이로드 스키마·재시도는 별도 ADR 또는 tasks 문서에서 정의.

---

Quality Gates: 구현 PR 시 `pytest`·관련 계약 테스트 통과 한 줄을 본 섹션 또는 [ai-extraction-schema.md](ai-extraction-schema.md)에 연동해 기록한다.
