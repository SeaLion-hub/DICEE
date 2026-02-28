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

## ContextVar와 백그라운드 태스크 (asyncio.create_task 사용 시 주의)

`session_scope(Propagation.REQUIRED)` 안에서 `asyncio.create_task(background_coro)`를 호출하면, **자식 태스크가 현재 컨텍스트를 복사**해 같은 `_session_context` 값을 갖게 됩니다. 요청이 끝나 세션이 닫힌 뒤에도 해당 백그라운드 태스크가 그 세션을 참조할 수 있어, 라이프사이클 오류·데드락·연결 풀 오염 가능성이 있습니다.

**권장**:

- 백그라운드 작업에 DB가 필요하면 `run_in_session(session_factory, fn)`처럼 **세션을 인자로 넘기거나**, 백그라운드 코루틴 내부에서 **새 세션을 열도록** 설계하세요.
- `session_scope`에 묶인 컨텍스트에 의존하는 코루틴을 `create_task`로 스폰하지 마세요.

---

## 적용 위치

- `app/core/database.py`: `session_scope()`, `transaction()`, `run_in_session()`, `Propagation` enum.
