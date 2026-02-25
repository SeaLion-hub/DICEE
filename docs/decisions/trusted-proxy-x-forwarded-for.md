# Trusted Proxy 및 X-Forwarded-For (ADR)

**상태**: 채택  
**배경**: 클라이언트가 조작 가능한 `X-Forwarded-For` 헤더를 검증 없이 신뢰하면 IP 스푸핑으로 차단/감사 우회가 가능하다.

---

## 결정

- **직전 피어(peer) IP 검증**: 앱이 받는 TCP 연결의 상대편 IP(`request.client.host`)가 **신뢰할 수 있는 프록시 목록(TRUSTED_PROXY_IPS)**에 있을 때만 `X-Forwarded-For` 헤더를 사용한다.
- **목록에 없거나 비어 있으면**: `X-Forwarded-For`는 무시하고 `request.client.host`만 클라이언트 IP로 사용한다.
- **역순 훑기**: 헤더 사용 시 `X-Forwarded-For`를 쉼표로 split한 리스트를 **오른쪽→왼쪽**으로 훑어, **신뢰 목록에 없는 첫 번째 IP**를 클라이언트 IP 후보로 채택한다. 모두 신뢰 목록에 있으면 **맨 왼쪽**(클라이언트에 가장 가까운) IP를 사용한다.
- **RFC 1918 필터링**: 후보 IP가 사설 대역(10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8)이면 클라이언트 IP로 사용하지 않고 `request.client.host`로 fallback 한다.
- **비정상 포맷 (fallback 금지)**: 신뢰 프록시 경유 요청에서 IP 개수 상한(32개 초과) 또는 비IP 문자열 포함 시 **fallback 하지 않는다**. **400 Bad Request**를 반환하고 **요청을 Drop**한다. (악의적 패킷 조작 또는 인프라 설정 오류로 간주.)

---

## 설정

- 환경 변수: `TRUSTED_PROXY_IPS` (쉼표 구분 IP 목록).
- 예: 로드밸런서가 `10.0.0.1`일 때 `TRUSTED_PROXY_IPS=10.0.0.1`.
- 비우면 프록시 뒤가 아니거나 검증을 원하지 않는 환경으로 간주되어, 항상 `request.client.host`만 사용.

---

## 적용 위치

- `app/core/network.py`의 `get_client_ip(request)`에서 위 로직 적용. `app/api/v1/auth.py` 등에서는 이 함수만 호출.
- IP 기반 차단·HMAC 저장·감사 로그 등 모든 클라이언트 IP 사용처가 이 함수를 통해 일관된 정책을 따른다.
