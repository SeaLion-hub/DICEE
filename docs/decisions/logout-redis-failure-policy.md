# 로그아웃 시 Redis Blocklist 실패 정책 (ADR)

**상태**: 채택  
**배경**: 로그아웃 시 DB에서 Refresh 토큰을 먼저 무효화한 뒤 Redis Blocklist에 Access jti를 등록한다. Redis 실패 시 Blocklist 등록이 되지 않아, Refresh는 이미 무효인데 Access는 TTL 만료까지 유효한 "비동기적 인증 상태 불일치"가 발생할 수 있다.

---

## 결정 (Option A: 엄격 유지)

- **서버 동작**: Redis Blocklist 등록 실패 시 **예외를 다시 던져** 클라이언트에 503(또는 해당 예외를 HTTP로 변환한 코드)을 반환한다. DB(Refresh 무효화)는 이미 commit된 상태이므로 재시도 시 동일 요청으로 다시 호출해도 **멱등**하다.
- **클라이언트 권장**: 로그아웃 API가 503을 반환하면 **동일한 요청(동일 Access/Refresh 사용)으로 재시도**한다. 재시도 시 서버는 DB는 이미 반영되어 있으므로 Refresh 무효화를 건너뛰고, Redis Blocklist 등록만 다시 시도한다.
- **문서화**: API 명세(또는 클라이언트 가이드)에 "로그아웃이 503을 반환하면 클라이언트는 동일 요청으로 재시도해야 하며, 재시도 시 멱등"을 명시한다.

---

## 대안 (Option B, 미채택)

- Redis 실패 시 로그만 하고 200 반환, 응답 헤더에 `X-Access-Blocklist-Applied: false` 등으로 "Access는 TTL 만료까지 유효할 수 있음"을 알리는 방식. 필요 시 설정 플래그로 나중에 도입 가능.
