# Trusted Proxy 및 X-Forwarded-For (ADR)

**상태**: 채택  
**배경**: 클라이언트가 조작 가능한 `X-Forwarded-For` 헤더를 검증 없이 신뢰하면 IP 스푸핑으로 차단/감사 우회가 가능하다.

---

## 결정

- **직전 피어(peer) IP 검증**: 앱이 받는 TCP 연결의 상대편 IP(`request.client.host`)가 **신뢰할 수 있는 프록시 목록(TRUSTED_PROXY_IPS)**에 있을 때만 `X-Forwarded-For` 헤더를 사용한다.
- **목록에 없거나 비어 있으면**: `X-Forwarded-For`는 무시하고 `request.client.host`만 클라이언트 IP로 사용한다.
- **헤더 사용 시**: `X-Forwarded-For`의 **첫 번째 값**(클라이언트에 가장 가까운 IP)을 사용한다. (쉼표 구분 체인에서 왼쪽이 클라이언트 측.)

---

## 설정

- 환경 변수: `TRUSTED_PROXY_IPS` (쉼표 구분 IP 목록).
- 예: 로드밸런서가 `10.0.0.1`일 때 `TRUSTED_PROXY_IPS=10.0.0.1`.
- 비우면 프록시 뒤가 아니거나 검증을 원하지 않는 환경으로 간주되어, 항상 `request.client.host`만 사용.

---

## 적용 위치

- `app/api/v1/auth.py`의 `_client_ip_from_request(request)`에서 위 로직 적용.
- IP 기반 차단·HMAC 저장·감사 로그 등 모든 클라이언트 IP 사용처가 이 함수를 통해 일관된 정책을 따른다.
