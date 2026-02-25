# 계획 평가 68/100 반영 — 보강 사항 요약

기존 계획([.cursor/plans](.cursor/plans) 또는 동일 이름 plan)에 아래 내용을 **반드시 반영**할 것. (계획 파일이 사용자 홈에 있어 본 문서로 보강 내용을 정리함.)

---

## 1. 아키텍처 (25/30)

### 1.1 Sentry — 임포트/설정 단계 오류 수집 트레이드오프 대안

- **필수**: lifespan 이동만이 아니라 **진입점 try-except 래핑** 또는 **최소 Sentry 부트스트랩**을 명시한다.
- 구체안: (A) uvicorn 로드 모듈 상단에서 `settings` 로드 후 `SENTRY_DSN` 있으면 `sentry_sdk.init(dsn=..., environment=...)` 최소 초기화 한 번 수행. (B) 앱 생성·라우터 등록 전체를 try/except로 감싸 미수집 예외가 없도록 한다.
- 추가로, uvicorn이 `app:app`을 로드하기까지 구간에서 발생하는 예외를 수집하기 위해 **진입점(run.py 등)에서의 로깅 인터셉터 설계**를 계획에 포함한다. 예: `run.py`에서 `sys.excepthook`·`threading.excepthook` 또는 로거 핸들러를 Sentry와 연동해, 앱 팩토리 실행 이전 단계의 치명적 예외도 수집하도록 정의한다.

### 1.2 DB 세션 — ContextVar는 "문서화"가 아닌 코드 레벨 강제

- **필수**: "문서화로 해결"이 아니라 **세션 팩토리를 주입받아 명시적으로 스코프를 관리하는 객체 도입**을 계획에 넣는다.
- 예: `SessionScope(session_factory)` 컨텍스트 매니저가 세션 생성·commit/rollback·close를 수행하고, ContextVar는 이 객체를 통해서만 set/reset되거나 제거하여 개발자가 직접 `_session_context.set/reset`을 호출할 수 없도록 API를 좁힌다.
- **중첩 트랜잭션(Propagation Policy)**: SessionScope/`transaction()`이 중첩될 때 내부 호출이 외부 스코프의 commit/rollback 상태를 오염시키지 않도록, REQUIRED/REQUIRES_NEW/NESTED 중 어떤 전파 정책을 쓸지 명시한다(예: 기본은 REQUIRED, REQUIRES_NEW는 savepoint 기반 등).
- Celery 등 비요청 컨텍스트에서는 세션을 인자로 명시 전달하되, 인터페이스가 복잡해져 다시 전역 상태에 손이 가지 않도록 `run_in_session(session_factory, fn)` 수준의 **단순한 진입점**만 제공하는 원칙을 계획에 적어둔다.

---

## 2. 보안 (26/30)

### 2.1 OAuth redirect_uri — 엄격한 스키마 정의

- **필수**: "방향"만이 아니라 **encoded characters**와 **case sensitivity**를 포함한 엄격한 스키마를 계획에 명시한다.
- Encoded characters: `urllib.parse.unquote`로 정규화 후 한 가지 표현만 허용(예: `%2F` vs `/` 우회 방지).
- Case sensitivity: scheme·host는 소문자 정규화; path는 프로젝트 정책으로 고정(대소문자 구분 또는 소문자 통일).
- 허용 구성요소: scheme(`https`만, `http`는 예외만), netloc, path; query·fragment는 검증 시 제거 또는 "있으면 거부".
- Double Encoding 방어: `unquote`를 몇 번까지 허용할지(예: 한 번만 허용하고 그 이후 `%`가 남아 있으면 거부, 또는 변화가 없을 때까지 반복 후 일정 횟수 초과 시 거부) 등 더블 인코딩 공격에 대한 명시적 처리 규칙을 추가한다.
- netloc 검증: 서브도메인 와일드카드를 허용할지 여부(`*.example.com` 허용 여부, 접미사 일치만 허용 등)를 ADR에 분명히 정의하고, 구현이 이에 맞춰 동작하도록 계획에 포함한다.
- query 거부 정책은 강력하지만, 실제 Google OAuth 리다이렉트에서 query를 사용하는 시나리오를 검토해, 필요 시 "허용 목록에 query까지 포함된 정확한 URI만 허용"과 같은 현실적인 절충안을 고려한다.

### 2.3 X-Forwarded-For — 모호한 "fallback" 제거, 명확한 알고리즘

- **필수**: Proxy Count 방식은 인프라 변경에 취약하므로 계획에서 제거하고, **역순 훑기 방식 하나만** 채택해 코드·ADR에 명시한다.
- 역순 훑기: `X-Forwarded-For` 리스트를 **오른쪽→왼쪽**으로 훑어 **신뢰 목록(trusted_proxy_ips)에 없는 첫 번째 IP**를 클라이언트 IP로 채택하고, 모두 신뢰 목록이면 맨 왼쪽 IP를 사용한다.
- RFC 1918 필터링: 후보 IP가 사설 대역(예: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8 등)이면 클라이언트 IP로 사용하지 않고 로깅만 하거나 `request.client.host`로 fallback 한다는 규칙을 알고리즘에 포함한다.
- 비정상 포맷: IP 개수 상한(예: 32개 초과) 또는 비IP 문자열 포함 시 `request.client.host`로 fallback — 이 조건을 ADR에 명시해 모호함을 제거한다.

---

## 3. 확장성 (14/20)

### 3.1 DB 풀 — "문서로 한계 인정"이 아닌 동적 조정/조회 검토

- **필수**: 정적 계산의 한계를 "인정하고 문서에 남기는" 유기가 아니라, 아래를 **검토·반영**한다.
  - **동적 db_max_connections 조회**: 부팅 시(또는 주기적) DB에서 `SHOW max_connections`(PostgreSQL) 등으로 실제 값을 조회해 `check_pool_budget()`에 사용. `DB_MAX_CONNECTIONS`는 fallback/오버라이드.
  - **동적 풀 사이징(Dynamic Pool Sizing) 검토**: 파드가 자원 제약(CPU/메모리) 또는 관측 지표(pool_wait_time 등)에 따라 풀 크기를 조정하는 로직 검토. ADR로 "1단계: 부팅 시 DB max_connections 조회, 2단계: 런타임 풀 튜닝(선택)"으로 나눌 수 있다.
- PGBouncer 등 DB 앞단 커넥션 풀러가 있는 엔터프라이즈 환경을 고려해, 애플리케이션 측 용량 계획이 실제 병목 계층(PGBouncer인지 DB인지)을 어떻게 인지하고 대응할지(예: PGBouncer 설정 값과의 관계, 어느 쪽 max_connections를 기준으로 삼을지)를 문서·설계에 통합된 관점으로 포함한다.

### 3.2 Redis SPOF — "복구 절차 문서"가 아닌 엔지니어링 대안

- **필수**: "장애 시 복구 절차 명시"는 운영 역할이므로, **개발 측 확장성 해결책**을 계획에 넣는다.
  - **Redis Sentinel 또는 Cluster** 도입 검토. Blocklist/Trigger Lock 키 설계가 클러스터와 충돌하지 않는지 검토.
  - **Blocklist 장애 시 Fail-open 격리 — Circuit Breaker**: Redis Blocklist 호출을 Circuit Breaker로 감싼다. 연속 실패가 임계치를 넘으면 "열림" 상태로 전환하고, 일정 시간 서명 검증만으로 통과(Fail-open). 임계치·열림 유지 시간·Half-open 간격을 환경 변수로 둔다.
- Redis Cluster 도입 시 멀티 키 연산(MGET 등)이 해시 슬롯 제약으로 깨지지 않도록, Blocklist/Trigger Lock용 키 네이밍 규칙(해시 태그 사용, 동일 슬롯에 묶기 등)에 대한 **키 설계 가이드라인**을 ADR에 추가한다.

---

## 4. 코드 가독성 (16/20)

### 4.1 allowed_origins — 레거시 즉시 제거 + 마이그레이션 전략

- **필수**: deprecated 형식을 남겨두지 않고 **명확한 마이그레이션 전략**으로 레거시(CSV)를 **즉시 제거**하는 방향을 계획에 명시한다.
  - (1) 한 릴리스 유예: CSV 입력 시 로그 경고 후 다음 버전에서 제거.
  - (2) 즉시 제거: CHANGELOG/DEPLOYMENT에 "ALLOWED_ORIGINS는 JSON 배열만 지원" 명시 후 코드에서 CSV 제거. 운영에 유리한 쪽 선택.

### 4.2 main.py 분리 — 공통 인터페이스 보장

- 진입점(main.py)을 순수하게 유지하기 위해 예외 핸들러를 별도 모듈로 분리하되, 분리된 핸들러들이 **공통 인터페이스**를 따르도록 계획에 명시한다.
- 예: 시그니처 `(request: Request, exc: Exception) -> JSONResponse`, 응답 스키마 `{ "detail": ..., "code": ... }`, 로깅·에러 코드 매핑 규칙을 한 곳에 정의하고, 모든 핸들러가 이를 따르도록 해 코드 추적 난이도를 높이지 않도록 한다.

---

## 5. 위험·제한 사항 문구 수정

- **SessionScope 도입** 시 기존 `transaction()`가 내부적으로 SessionScope를 쓰는 호환 레이어를 두면 단계적 전환이 가능하다.
- **Redis Sentinel/Cluster**는 인프라 변경이 필요하므로, Circuit Breaker 도입을 선행하고 Sentinel/Cluster는 별도 ADR·스프린트로 진행할 수 있다.
- 이 계획대로 진행하면 **"문서화에 의존한 유기"**와 **"확장성·아키텍처의 코드 레벨 미흡"**을 해소할 수 있다.

---

이 문서는 계획 평가 68/100 피드백을 반영한 **보강 체크리스트**이다. 실제 계획 파일을 수정할 때 위 항목을 반드시 반영하면 된다.

---

## Go-Live Checklist (참조)

베타 → 프로덕션 전환 시 **부하 테스트·통과 기준·장애 훈련** 시나리오 및 **게이트웨이 타임아웃** 정책은 [DEPLOYMENT.md — Go-Live 검증](DEPLOYMENT.md#go-live-검증-부하-테스트장애-훈련) 섹션을 따른다. 통과 기준: 오류율 &lt; 1%, Auth p95 &lt; 500ms, DB active connection &lt; App_budget × 0.7.
