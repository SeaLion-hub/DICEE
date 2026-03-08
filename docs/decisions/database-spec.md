# 데이터베이스 설계 명세서 (Technical Specification) — Final Delivery

**버전**: 7.0 (Masterpiece - Zero Defect Architecture)

**원칙**: 본 명세서는 타협 불가능한 단일 진실 공급원(SSOT)이다. 애플리케이션의 편의를 위해 DB의 무결성, 가용성, 보안 원칙을 훼손하는 것을 엄격히 금지한다.

---

## 1. 공통 규칙 및 식별자

### 1.1 PK 및 타임스탬프

* **PK**: 모든 메인 엔티티는 **UUID**를 사용한다.
* **UUID 생성**: 애플리케이션 레벨 생성을 엄격히 금지한다. DB 엔진이 직접 발급하도록 한다. Railway 등 기본 PostgreSQL 환경 호환을 위해 **`gen_random_uuid()`**(UUID v4)를 사용한다. (pg_uuidv7 확장이 설치된 환경에서는 `uuid_generate_v7()` 사용 가능.)
* **Base 모델**: `created_at`, `updated_at` (TIMESTAMPTZ, NOT NULL)을 모든 테이블이 공통 상속한다.

### 1.2 updated_at 무결성

* **단일 확정 정책**: 애플리케이션의 갱신 로직을 신뢰하지 않는다. **오직 DB 트리거**로만 `updated_at`을 갱신한다.
* **구현**: 모든 테이블에 `BEFORE UPDATE FOR EACH ROW EXECUTE FUNCTION set_updated_at()` 트리거를 강제한다.

---

## 2. 데이터 상태 동기화 및 복구 파이프라인 (CDC & Snapshotting)

### 2.1 Soft Delete 정책

* **단일 확정 정책**: 부모 엔티티(`colleges`, `users`, `notices`)에만 `deleted_at` (TIMESTAMPTZ) 컬럼이 존재한다.
* **금지 사항**: 하위 테이블에 `deleted_at`을 복제하거나, 상위 데이터 삭제 시 하위 테이블에 CASCADE UPDATE 쿼리를 날려 MVCC Dead Tuple을 양산하는 행위를 전면 금지한다.

### 2.2 비동기 상태 전파 (Debezium CDC)

* **구현**: PostgreSQL의 **Logical Replication Slot**을 생성하고, Debezium이 WAL(Write-Ahead Log)을 테일링하여 데이터 변경(Soft Delete 포함) 이벤트를 Kafka로 발행한다. DB 디스크 Full 방어를 위해 `max_slot_wal_keep_size` 파라미터를 하드코딩한다.
* **장애 복구 파이프라인 (Incremental Snapshotting)**:
* `max_slot_wal_keep_size` 임계치 도달로 인해 WAL 슬롯이 무효화(Dropped)될 경우, CDC 이벤트는 유실된다.
* 인프라 모니터링이 Slot Drop을 감지하면 즉각 PagerDuty Critical Alert를 울림과 동시에 AWS Lambda를 트리거하여 Kafka Connect API의 **"Ad-hoc Incremental Snapshot(점진적 스냅샷)"**을 실행한다. 이를 통해 DB 메인 트랜잭션 부하를 최소화하면서 유실된 상태를 하위 시스템(Kafka)으로 완벽히 재동기화한다.

---

## 3. PII 감사 로그 및 보안 (Zero Data Loss & WAF)

### 3.1 PII 사이드카 로깅 (Sidecar Pattern)

* **단일 확정 정책**: PII 접근 시 애플리케이션 메인 스레드에서 Kafka로 동기 전송(`acks=all`)하는 병목 로직은 폐기한다. 메인 스레드 I/O Block 시간은 0ms여야 한다.
* **구현**:
* 애플리케이션은 로컬 `tmpfs`(메모리 기반 휘발성 볼륨)에 Append-only 방식으로 접근 로그를 비동기 기록한다.
* 동일 Pod 내의 **Vector.dev 또는 Fluent Bit 사이드카(Sidecar)**가 해당 로그를 테일링하여 Kafka로 안전하게 전송(`acks=all`, `retries=infinity`)한다.
* 사이드카 버퍼 리밋과 50MB 도달 시 덮어쓰기(Log Rotation) 정책을 적용하여 OOM을 방지한다.

### 3.2 HMAC IP 암호화 및 복합 Rate Limiting

* **IP 저장**: 평문 IP 저장을 금지한다. DB에는 `ip_hmac` (VARCHAR(64), HMAC-SHA256)과 `ip_hmac_key_version` (VARCHAR(32))만 저장한다.
* **API Gateway + WAF 방어**:
* API Gateway(Kong/APISIX) 레벨에서 **`IP + target_user_id` 복합 키(Composite Key)** 기준 Redis Token Bucket을 적용한다. (초당 2회 / 분당 20회 임계치)
* 임계치 초과 시 `429 Too Many Requests` 반환과 동시에 Event-driven으로 Cloudflare WAF API를 호출하여 해당 IP에 **최상위 난이도의 CAPTCHA 챌린지**를 강제한다.

---

## 4. 매칭 엔진과 동시성 제어 (AST Rule Engine & Deadlock-Free)

### 4.1 매칭 엔진 최적화와 암호화 경계 (user_profiles)

* **분리 저장**:
* `encrypted_data` (BYTEA): 소득분위, 연락처 등 고도 민감 정보(순수 PII) 전용 보관. KMS를 통해 암/복호화된다.
* `matching_profile` (JSONB): 학과, 학년, 학점 구간 등 AST 룰 엔진이 즉각 필터링에 사용할 수 있는 비식별 인덱싱 데이터.

* **데이터 오염 방어**: `matching_profile` 내에 PII가 유입되는 것을 DB CHECK 제약 조건과 애플리케이션 레벨의 Masking 파이프라인으로 이중 차단한다.

### 4.2 완벽한 낙관적 락(Optimistic Locking)

* **구현**: `user_profiles` 업데이트 시 오직 `kms_key_version`을 이용한 **낙관적 락**만 사용한다. (`SELECT FOR UPDATE` 절대 금지)
* **쿼리**: `UPDATE user_profiles SET ... WHERE user_id = :id AND kms_key_version = :old_version`. 충돌(0행 갱신) 발생 시 워커는 즉각 포기, 사용자는 1회 재시도 후 409 반환.

---

## 5. 파티셔닝 및 스토리지 분리

### 5.1 대용량 시계열 테이블 파티셔닝 및 Global Unique 방어

* **구현**: `crawl_logs`, `crawl_runs` 테이블은 **`created_at`, `started_at` 기준 월 단위 파티셔닝(Table Partitioning)**을 강제한다.
* **Global Unique Lookup 분리**: 파티션 테이블은 파티션 키가 포함되지 않은 컬럼에 대해 Unique 제약을 걸 수 없다. `celery_task_id`의 글로벌 멱등성 보장을 위해 별도의 비파티셔닝 Lookup 테이블(`crawl_run_tasks`)을 구축한다.
* **Autovacuum 최적화**: 파티션 테이블에 `autovacuum_vacuum_scale_factor = 0.01` (1%)을 적용. 12개월 경과 파티션은 `DROP PARTITION`으로 즉시 물리적 삭제.

### 5.2 스토리지 분리

* **notice_contents**: 메인 DB에 TEXT 본문을 넣는 것을 금지한다. 수집 즉시 S3(오브젝트 스토리지)에 본문을 저장 후, DB에는 `content_url` (VARCHAR(2048))만 남긴다. 검색은 S3/Elasticsearch로 위임한다.

---

## 6. 테이블 DDL 명세 (The Core)

*이하 모든 테이블에는 `BEFORE UPDATE` 트리거(`set_updated_at`)가 기본 적용된다.*

### 6.1 colleges (게시판 소스)

| 컬럼 | 타입 | 제약 |
| --- | --- | --- |
| id | UUID | PK, DEFAULT gen_random_uuid() |
| name | VARCHAR(255) | NOT NULL |
| external_id | VARCHAR(255) | NOT NULL |
| is_crawl_enabled | BOOLEAN | NOT NULL DEFAULT true |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| deleted_at | TIMESTAMPTZ | NULL |

* **Partial Unique Index**: `CREATE UNIQUE INDEX uq_colleges_external_id ON colleges(external_id) WHERE deleted_at IS NULL;`

### 6.2 notices (공지사항 메인)

| 컬럼 | 타입 | 제약 |
| --- | --- | --- |
| id | UUID | PK, DEFAULT gen_random_uuid() |
| college_id | UUID | NOT NULL, FK(colleges.id), INDEX |
| external_id | VARCHAR(512) | NOT NULL |
| title | VARCHAR(512) | NOT NULL |
| url | VARCHAR(2048) | NULL |
| published_at | TIMESTAMPTZ | NULL, INDEX |
| category | VARCHAR(64) | NULL, INDEX |
| sub_category | VARCHAR(64) | NULL |
| content_hash | VARCHAR(64) | NULL, INDEX |
| eligibility | JSONB | NULL |
| hashtags | JSONB | NULL |
| ai_status | VARCHAR(20) | NOT NULL DEFAULT 'pending', CHECK IN ('pending', 'processing', 'done') |
| ai_extracted_json | JSONB | NULL |
| is_manual_edited | BOOLEAN | NOT NULL DEFAULT false |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| deleted_at | TIMESTAMPTZ | NULL |

* **Partial Unique Index**: `CREATE UNIQUE INDEX uq_notices_college_external ON notices(college_id, external_id) WHERE deleted_at IS NULL;`
* **JSONB 물리적 방어 제약 (CHECK)**:
* `CHECK (eligibility IS NULL OR (jsonb_typeof(eligibility) = 'array' AND jsonb_array_length(eligibility) <= 50))`
* `CHECK (ai_extracted_json IS NULL OR (jsonb_typeof(ai_extracted_json) = 'object'))`

* **GIN Index**: `eligibility`, `hashtags` (fastupdate=on, gin_pending_list_limit=4MB)
* **이미지 저장**: 공지 이미지는 스토리지(S3/로컬)에 파일로 업로드하고, `images` JSONB에는 URL만 저장. base64는 크롤 파이프라인에서 업로드 후 URL로 치환.

### 6.3 notice_contents (본문 S3 분리)

| 컬럼 | 타입 | 제약 |
| --- | --- | --- |
| notice_id | UUID | PK, FK(notices.id) ON DELETE CASCADE |
| content_url | VARCHAR(2048) | NOT NULL |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

*(deleted_at 없음. 데이터 가시성은 notices.deleted_at에 위임)*

### 6.4 notice_schedules (캘린더 예외 완벽 지원)

| 컬럼 | 타입 | 제약 |
| --- | --- | --- |
| id | UUID | PK, DEFAULT gen_random_uuid() |
| notice_id | UUID | NOT NULL, FK(notices.id), INDEX |
| schedule_type | VARCHAR(32) | NOT NULL |
| start_at | TIMESTAMPTZ | NULL |
| end_at | TIMESTAMPTZ | NULL |
| is_all_day | BOOLEAN | NOT NULL DEFAULT false |
| is_tbd | BOOLEAN | NOT NULL DEFAULT false |
| is_always_open | BOOLEAN | NOT NULL DEFAULT false |
| schedule_text_fallback | VARCHAR(255) | NULL |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

* **상호 배타적 무결성 제약 (State Transition Constraints)**:
* `CONSTRAINT chk_schedule_time CHECK ((is_tbd = true OR is_always_open = true) OR start_at IS NOT NULL)` (미정/상시가 아니면 시작일 필수)
* `CONSTRAINT chk_schedule_exclusive CHECK (NOT (is_tbd = true AND is_always_open = true))` (미정이면서 상시일 수 없음)
* `CONSTRAINT chk_tbd_null CHECK (is_tbd = false OR (start_at IS NULL AND end_at IS NULL))` (미정이면 날짜는 무조건 NULL)

### 6.5 users (사용자 계정)

| 컬럼 | 타입 | 제약 |
| --- | --- | --- |
| id | UUID | PK, DEFAULT gen_random_uuid() |
| provider | VARCHAR(32) | NOT NULL, INDEX |
| provider_user_id | VARCHAR(256) | NOT NULL, INDEX |
| email | VARCHAR(256) | NULL |
| name | VARCHAR(256) | NULL |
| refresh_token_version | INTEGER | NOT NULL DEFAULT 0 |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| deleted_at | TIMESTAMPTZ | NULL |

* **Partial Unique Index**: `CREATE UNIQUE INDEX uq_users_provider_uid ON users(provider, provider_user_id) WHERE deleted_at IS NULL;`

### 6.6 user_profiles (비식별화 데이터 분리 및 AST 연산용)

| 컬럼 | 타입 | 제약 |
| --- | --- | --- |
| user_id | UUID | PK, FK(users.id) |
| encrypted_data | BYTEA | NOT NULL (순수 PII 전용, KMS 암호화) |
| matching_profile | JSONB | NOT NULL DEFAULT '{}'::jsonb (AST 매칭용 비식별 스탯) |
| kms_key_version | VARCHAR(64) | NOT NULL |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| updated_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

* **JSONB 쓰레기통화 방지 제약**: `CONSTRAINT chk_matching_profile_schema CHECK (jsonb_typeof(matching_profile) = 'object' AND NOT (matching_profile ? 'phone' OR matching_profile ? 'ssn'))`
* **GIN Index**: `CREATE INDEX idx_user_profiles_matching ON user_profiles USING GIN (matching_profile);`

### 6.7 user_calendar_events (사용자 캘린더)

| 컬럼 | 타입 | 제약 |
| --- | --- | --- |
| id | UUID | PK, DEFAULT gen_random_uuid() |
| user_id | UUID | NOT NULL, FK(users.id), INDEX |
| notice_schedule_id | UUID | NOT NULL, FK(notice_schedules.id), INDEX |
| custom_title | VARCHAR(512) | NULL |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

* **Unique Index**: `CREATE UNIQUE INDEX uq_user_calendar_user_schedule ON user_calendar_events(user_id, notice_schedule_id);`

### 6.8 keyword_subscriptions (구독 키워드)

| 컬럼 | 타입 | 제약 |
| --- | --- | --- |
| id | UUID | PK, DEFAULT gen_random_uuid() |
| user_id | UUID | NOT NULL, FK(users.id), INDEX |
| keyword_hash | VARCHAR(64) | NOT NULL, INDEX |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

* **Unique Index**: `CREATE UNIQUE INDEX uq_keyword_subscriptions_user_hash ON keyword_subscriptions(user_id, keyword_hash);`

### 6.9 crawl_run_tasks (Global Unique Lookup Table)

| 컬럼 | 타입 | 제약 |
| --- | --- | --- |
| celery_task_id | UUID | PK (Global Unique 멱등성 보장) |
| run_id | UUID | NOT NULL, INDEX |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

* **역할**: 파티셔닝된 `crawl_runs` 테이블 삽입 전 멱등성 보장. (이 테이블에 INSERT 성공 시에만 파티션 적재)

### 6.10 crawl_runs (Partitioned)

| 컬럼 | 타입 | 제약 |
| --- | --- | --- |
| id | UUID | NOT NULL, DEFAULT gen_random_uuid() |
| started_at | TIMESTAMPTZ | NOT NULL |
| college_id | UUID | NOT NULL, INDEX |
| finished_at | TIMESTAMPTZ | NULL |
| status | VARCHAR(32) | NOT NULL, CHECK IN ('running', 'success', 'failed') |
| total_count | INTEGER | NOT NULL DEFAULT 0 |
| success_count | INTEGER | NOT NULL DEFAULT 0 |
| fail_count | INTEGER | NOT NULL DEFAULT 0 |

* **PK 정의**: `PRIMARY KEY (id, started_at)` (파티션 키 포함 필수)
* **설정**: `PARTITION BY RANGE (started_at)`. 월별 파티션 생성.

### 6.11 crawl_logs (Partitioned)

| 컬럼 | 타입 | 제약 |
| --- | --- | --- |
| id | UUID | NOT NULL, DEFAULT gen_random_uuid() |
| created_at | TIMESTAMPTZ | NOT NULL |
| run_id | UUID | NOT NULL, INDEX |
| severity | VARCHAR(16) | NOT NULL, CHECK IN ('INFO', 'WARN', 'ERROR') |
| message | VARCHAR(2000) | NULL |
| stack_trace | TEXT | NULL |

* **PK 정의**: `PRIMARY KEY (id, created_at)`
* **설정**: `PARTITION BY RANGE (created_at)`. 월별 파티션 생성.

---

## 7. Materialized View 명세 & SLA (CQRS 읽기 전용)

* **목적**: `notice_schedules`를 조회할 때 부모 엔티티(`notices`, `colleges`)의 `deleted_at`을 실시간 JOIN 하는 부하를 원천 제거.
* **뷰 정의 (`active_notice_schedules_mv`)** (title은 notices에서 가져옴):

```sql
CREATE MATERIALIZED VIEW active_notice_schedules_mv AS
SELECT
    ns.id AS schedule_id,
    ns.notice_id,
    n.college_id,
    ns.start_at,
    ns.end_at,
    ns.is_all_day,
    ns.is_tbd,
    ns.is_always_open,
    ns.schedule_text_fallback,
    n.title
FROM notice_schedules ns
INNER JOIN notices n ON ns.notice_id = n.id AND n.deleted_at IS NULL
INNER JOIN colleges c ON n.college_id = c.id AND c.deleted_at IS NULL;
```

* **Unique Index (CONCURRENTLY 필수 요건)**:
`CREATE UNIQUE INDEX uq_active_schedules_mv_id ON active_notice_schedules_mv(schedule_id);`
* **갱신 로직**: 애플리케이션 또는 DB Task가 주기적으로 `REFRESH MATERIALIZED VIEW CONCURRENTLY active_notice_schedules_mv;` 실행.

### 7.1 비즈니스 SLA (Stale-If-Error Tolerance)

> **[Fallback Policy: Eventual Consistency Tolerance]**
> "Materialized View 갱신(Cron/Worker)이 실패하여 데이터 지연(Staleness)이 1분(SLA)을 초과하더라도, 읽기 API는 절대 503 에러를 반환하거나 동기식 JOIN 쿼리로 Fallback 하지 않는다.
> 대신, **기존의 Stale Data(오래된 뷰)를 클라이언트에게 그대로 200 OK로 반환(Serve Stale)**하여 99.99%의 읽기 가용성을 사수한다. 이와 동시에 뷰 갱신 실패 메트릭은 PagerDuty Critical Alert로 승급되어 엔지니어가 수동 개입한다."

---

## 8. 검색 인덱싱 파이프라인 (Search & Indexing)

본문 데이터(notice_contents)가 S3로 분리됨에 따라, 검색 성능 확보를 위한 별도의 인덱싱 워커를 다음과 같이 정의한다.

### 8.1 검색 엔진 연동 (Elasticsearch/OpenSearch)

* **목적**: S3에 저장된 비정형 HTML/TEXT 데이터에 대한 고속 전문 검색(Full-text Search) 제공.
* **구현 방식 (Event-driven Indexing)**:
* **CDC Trigger**: notice_contents 테이블에 새로운 content_url이 INSERT 되면 Debezium이 이벤트를 Kafka로 발행한다.
* **Indexing Worker**: 전용 Celery 워커가 이 이벤트를 구독하여 S3에서 본문을 Fetch 한다.
* **Text Processing**: HTML 태그 제거 및 형태소 분석(Nori 등) 후 Elasticsearch의 notices_index에 인덱싱한다.
* **SLA**: 본문 수집 후 검색 엔진 반영까지 최대 5초 이내 완료를 보장한다.

### 8.2 DB 기반 메타데이터 검색 (Fallback)

* **대상**: 제목(title), 카테고리(category), 단과대(college_id).
* **인덱싱**: notices 테이블의 title 컬럼에 대해 PostgreSQL **Trigram Index (pg_trgm)**를 생성하여 본문 검색이 아닌 메타데이터 기반의 접미사/부분 일치 검색은 DB 내에서 즉시 처리 가능하도록 지원한다.
* **DDL**: `CREATE EXTENSION IF NOT EXISTS pg_trgm;` 후 `CREATE INDEX idx_notices_title_trgm ON notices USING gin (title gin_trgm_ops);`

---

## 마지막 경고 및 가이드라인

* **Logical Replication Slot 위험성**: max_slot_wal_keep_size를 설정하더라도, Debezium 워커가 죽어있는 동안 WAL이 해당 사이즈를 넘어가면 슬롯이 무효화됩니다. 이때는 반드시 2.2절에 명시된 Incremental Snapshot을 수동/자동으로 트리거해야만 데이터 유실을 막을 수 있습니다.

* **S3 Pre-signed URL 활용**: notice_contents.content_url을 앱에서 클라이언트에 직접 노출할 때는 보안을 위해 S3 Pre-signed URL을 생성하여 단기 만료(예: 10분) 링크로 제공하십시오.

* **Materialized View 인덱스**: active_notice_schedules_mv의 검색 성능을 위해 title이나 start_at에 대한 추가 인덱스 생성을 고려하십시오.

---

*(End of Document - Ready for Production Drop)*
