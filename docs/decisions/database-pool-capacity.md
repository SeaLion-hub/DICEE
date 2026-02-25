# DB 연결 풀 및 용량 계획 (결정 요약)

**관련 문서**: [DEPLOYMENT.md](../DEPLOYMENT.md) — "DB 연결 수 및 용량 계획" 섹션에서 공식·예산·스케일 가이드와 환경 변수 목록을 유지한다.

---

## 1. 풀 설정 명시화

* **결정**: Async API 풀과 Celery Sync 풀의 `pool_size`, `max_overflow`, `pool_timeout`(및 Sync의 `pool_recycle`)을 코드에 **명시**하고, 환경 변수로 오버라이드 가능하게 한다.
* **이유**: SQLAlchemy 기본값에 의존하면 프로세스 수 증가 시 **총 연결 수가 예측 불가**해, DB `max_connections` 초과·풀 포화 리스크가 커진다. 명시 시 capacity planning이 가능하다.

---

## 2. 예산 검사 산식 (실제 풀 설정값 기준)

* **결정**: 부팅 시 예산 검사는 **실제 설정값**(`db_pool_size_async`, `db_pool_max_overflow_async`, `db_pool_size_sync`, `db_pool_max_overflow_sync`)으로 Peak를 계산한다. 즉 `API_conn = N_api_instances × N_uvicorn_workers × (pool_size_async + max_overflow_async)`, `Worker_conn = N_worker_instances × N_celery_concurrency × (pool_size_sync + max_overflow_sync)`, `Peak_pool_conn = (API_conn + Worker_conn) × DEPLOY_SURGE_FACTOR`, 통과 조건 `Peak_pool_conn ≤ App_budget`.
* **이유**: 운영에서 풀 크기를 변경하면 예산 검사 결과가 그에 맞게 반영되어 용량 판단이 정확해진다. **프로파일 R**(4, 6, 2, 0)은 권장 참고값으로 코드 상수 `POOL_PROFILE_R`에만 남겨 두며, 예산 검사에는 사용하지 않는다.

---

## 3. 안전 예산 (App_budget)

* **결정**: `App_budget = floor((DB_max_connections - Reserved) × 0.7)` 로 계산한다. **Reserved**는 PostgreSQL 등에서 슈퍼유저/관리용으로 예약된 연결 수(일반적으로 2~3).
* **이유**: `DB_max × 0.7`만 쓰면 예약 연결을 빼지 않아 과대 추정이 되고, 마이그레이션/psql/모니터링/예외 버스트용 여유(20~30%)를 남겨야 한다.

---

## 4. 피크 계산 (Deploy_surge_factor)

* **결정**: 롤링 배포·오토스케일 구간에 **순간 피크**를 고려해 `Peak_pool_conn = Total_pool_conn × Deploy_surge_factor`(기본 2)를 사용한다.
* **이유**: 정상 상태만 보면 Total=17 등으로 여유 있어 보이지만, 배포/스케일 시 **순간 2배**까지 늘 수 있어, 예산 조건은 `Peak_pool_conn ≤ App_budget`으로 둔다.

---

## 5. Celery 모드별 연결 수

* **결정**: 문서에 **`--pool=solo` vs `--pool=prefork`** 계산식을 분리해 명시한다. prefork는 자식 프로세스마다 풀 1개이므로 `Worker_conn = N_worker_instances × N_celery_concurrency × (P_sync + O_sync)`.
* **이유**: Windows는 solo 필수, Linux는 기본 prefork. 모드를 바꾸거나 concurrency를 올리면 연결 수가 선형 증가하므로, 스케일 전에 용량을 다시 계산해야 한다.

---

## 6. 과다 설정 방지 (부팅 시 예산 검사)

* **결정**: `DB_MAX_CONNECTIONS`가 설정된 경우, 부팅 시 `Peak_pool_conn > App_budget`이면 **기본은 로그 warning**, `DB_POOL_STRICT_BUDGET=true`이면 **부팅 실패**로 둔다.
* **이유**: 풀·인스턴스 수를 환경 변수로 키우다 보면 예산을 넘길 수 있어, **과도한 값**에 대한 방지 장치가 필요하다. 선택적 strict 모드로 운영 정책에 맞출 수 있다.

### 6.1 동적 max_connections 조회 및 effective_max_connections

* **결정**: `verify_db_connection()` 성공 시 PostgreSQL `SELECT current_setting('max_connections')::int`로 **실제 DB max_connections**를 조회해 저장한다. 예산 검사에 사용하는 **effective_max_connections**는 **환경 변수 `DB_MAX_CONNECTIONS`가 설정되어 있으면 그 값을 사용(운영 오버라이드)**하고, 미설정 시에만 조회한 `get_resolved_max_connections()`를 사용한다.
* **이유**: DB 쪽 설정 변경 시 앱이 이를 반영할 수 있다. 운영에서 명시적으로 상한을 고정하고 싶을 때는 `DB_MAX_CONNECTIONS`로 오버라이드한다.
* **적용**: lifespan에서 `verify_db_connection()` 후 `effective_max_conn = settings.db_max_connections if settings.db_max_connections is not None else get_resolved_max_connections()`로 계산하고, `check_pool_budget(effective_max_conn)` 호출. `DB_POOL_STRICT_BUDGET=true`이면 예산 초과 시 부팅 실패(RuntimeError), `false`이면 critical 로그 및 Sentry(`context=db_capacity`) 후 부팅 계속.

---

## 7. Statement timeout (장기 쿼리 방어)

* **결정**: 연결 단위로 PostgreSQL `statement_timeout`을 설정한다. 한 쿼리가 풀을 오래 잡아 Connection Pool Exhaustion으로 서비스 전체가 멈추는 것을 방지한다.
* **구현**: Async 엔진(postgresql+psycopg) 생성 시 `connect_args={"options": "-c statement_timeout=<ms>"}`로 전달. psycopg3는 `server_settings` 미지원이므로 libpq `options` 사용. `DB_STATEMENT_TIMEOUT_MS` 환경 변수(기본 30000ms)로 설정 가능.
* **이유**: 크롤링·복잡한 조인 등으로 장기 실행 쿼리가 나가면 해당 연결이 TTL 만료까지 풀에 묶이므로, 서버 레벨에서 실행 시간 상한을 두는 것이 안전하다.

---

## 8. 관측성 (권장 메트릭)

* **결정**: 풀 포화 조기 감지를 위해 **db_pool_checked_out**, **pool_wait_time**, **timeout_count** 등 메트릭 추가를 문서에 권장 목록으로 포함한다. 구현은 SQLAlchemy 이벤트 또는 커스텀 래퍼로 추후 진행.
* **이유**: 풀 포화는 **로그만**으로는 늦게 잡히므로, 메트릭 수집·알림(Sentry/메트릭 수집기 연동)으로 대응할 수 있게 한다.

---

총 연결 수 계산·기본값·예시는 **DEPLOYMENT.md**의 "DB 연결 수 및 용량 계획"을 참조한다.
