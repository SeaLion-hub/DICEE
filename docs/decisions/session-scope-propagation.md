# SessionScope 및 중첩 트랜잭션 전파 (ADR)

**상태**: 채택  
**배경**: ContextVar를 직접 set/reset하면 비동기 환경에서 컨텍스트 누수·오염 위험이 있다. 세션 스코프를 명시적으로 관리하는 객체와 전파 정책이 필요하다.

---

## 결정

- **SessionScope**: 세션 팩토리를 주입받아 스코프를 관리하는 **유일한 진입점**. ContextVar는 SessionScope 내부에서만 set/reset되며, 개발자가 `_session_context`를 직접 호출하지 않는다.
- **전파 정책(Propagation)**:
  - **REQUIRED**: 기존 세션 있으면 참여, 없으면 새로 생성. 내부 commit/rollback은 외부 스코프를 오염시키지 않음(외부가 commit/rollback 소유).
  - **REQUIRES_NEW**: 항상 새 세션. 독립 commit/rollback. ContextVar에 넣지 않음.
  - **NESTED**: 기존 세션 있으면 savepoint 사용, 없으면 REQUIRED와 동일.
- **transaction()**: `SessionScope(maker, Propagation.REQUIRED)` 호환 레이어. 서비스 레이어에서는 `transaction()` 또는 `session_scope(maker, propagation)` 사용.
- **비요청 컨텍스트(Celery 등)**: `run_in_session(session_factory, fn)` 단일 진입점. `fn(session)` 시그니처. 전역 상태에 손대지 않고 세션만 명시 전달.

---

## 적용 위치

- `app/core/database.py`: `session_scope()`, `transaction()`, `run_in_session()`, `Propagation` enum.
