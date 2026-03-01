# 로그아웃 시 Redis Blocklist 실패 정책 (ADR)

**상태**: 채택  
**배경**: 로그아웃 시 **Redis Blocklist에 Access jti를 먼저 등록**한 뒤 DB에서 Refresh 토큰을 무효화(commit)한다. Redis 실패 시 503을 반환하고 DB는 건드리지 않아, "DB는 로그아웃됐는데 Access는 유효"인 최악의 불일치를 피한다. Redis 성공 후 DB 실패 시에는 Access는 이미 블록되어 있어 보안상 유리하다.

---

## 결정 (Option A: Redis 먼저)

- **서버 동작**: **Redis Blocklist 등록을 먼저 시도**한다. 실패 시 503 반환(DB 로직 미실행). 성공 시에만 `logout_user` + `commit` 수행. DB 예외 시 `rollback` 후 재발생. Redis 등록 성공 후 DB commit이 실패하면, 동일 Access로 재시도 시 이미 blocklist에 있어 **401**이 발생할 수 있음(재시도 계약 참고).
- **클라이언트 권장**  
  - **방어적 동작(권장·필수)**: 로그아웃 요청을 보낸 후에는 **2xx/503/네트워크 에러 등 응답 코드와 관계없이** 로컬 스토리지/쿠키의 Access·Refresh 토큰을 삭제한다. 서버 상태가 꼬였을 때에도 클라이언트가 오래된 토큰을 들고 있지 않도록 한다.  
  - **재시도**: 503이면 서버 일시 장애이므로 잠시 후 재시도(이때 클라이언트는 이미 토큰 파기 권장). **Redis 먼저** 순서이므로 503은 Redis 실패 → 동일 Access로 재시도 시 Blocklist 등록만 다시 시도. DB 실패로 5xx인 경우, 동일 Access로 재시도하면 이미 blocklist에 있어 **401**이 발생할 수 있음.
- **문서화**: API 명세(또는 클라이언트 가이드)에 "로그아웃 요청 후 응답과 관계없이 로컬 토큰 파기" 및 "503 시 재시도·재시도 시 멱등"을 명시한다.

---

## 대안 (Option B, 미채택)

- Redis 실패 시 로그만 하고 200 반환, 응답 헤더에 `X-Access-Blocklist-Applied: false` 등으로 "Access는 TTL 만료까지 유효할 수 있음"을 알리는 방식. 필요 시 설정 플래그로 나중에 도입 가능.
