# JWT RS256 도입 (ADR)

**상태**: 채택  
**배경**: HS256은 대칭키를 사용해 인증 서버와 토큰 검증 주체가 동일한 시크릿을 공유해야 한다. 마이크로서비스·다중 서비스에서 토큰을 검증하려면 시크릿을 널리 배포해야 하는 아키텍처 결함이 있다. RS256(비대칭키)을 쓰면 **Private Key**는 발급 서버만 보유하고, **Public Key**만 검증 서비스에 배포하면 되어 확장성이 좋다.

---

## 결정

- **알고리즘**: JWT 발급·검증 시 **RS256**을 지원한다. 설정으로 **HS256**(기존)과 **RS256**을 선택할 수 있다.
- **키 보관**:
  - **Private Key**: PEM 형식. 환경 변수(예: `JWT_PRIVATE_KEY_PEM`) 또는 시크릿 매니저에 보관. 발급 서버(이 API)만 보유.
  - **Public Key**: PEM 형식. 환경 변수(예: `JWT_PUBLIC_KEY_PEM`) 또는 JWKS URL로 제공. 검증만 하는 다른 서비스는 Public Key만 갖으면 된다.
- **전환**: `JWT_PRIVATE_KEY_PEM`·`JWT_PUBLIC_KEY_PEM`이 모두 설정되어 있으면 RS256 사용, 아니면 기존처럼 `JWT_SECRET`으로 HS256 사용(Fail-fast 정책 유지).

---

## 키 생성 (배포 시)

```bash
# RSA 2048비트 키 쌍 생성
openssl genrsa -out private.pem 2048
openssl rsa -in private.pem -pubout -out public.pem
```

Private Key 내용을 한 줄로(줄바꿈을 `\n`으로) 환경 변수에 넣거나, Railway 등에서 시크릿으로 등록한다. Public Key는 검증만 하는 서비스에 동일하게 등록한다.

---

## 배포

- [DEPLOYMENT.md](../DEPLOYMENT.md)의 환경 변수 섹션에 `JWT_PRIVATE_KEY_PEM`, `JWT_PUBLIC_KEY_PEM` 설명 및 RS256 선택 시 `JWT_SECRET` 불필요함을 명시한다.

---

## 2026-02-27 Update

- Added `JWT_SIGNING_MODE` (`auto|hs256|rs256`).
- `auto` precedence is explicitly fixed to **RS first**:
  1. If a complete RS key pair exists (`JWT_PRIVATE_KEY_PEM` + `JWT_PUBLIC_KEY_PEM`), use `RS256`.
  2. Otherwise, if `JWT_SECRET` exists, use `HS256`.
  3. Otherwise fail-fast at boot.
- Encode and decode now use the same resolver; RS mode is selected only when the key pair is complete.
- `rs256` mode fails fast when RS key material is incomplete.
- `hs256` mode fails fast when `JWT_SECRET` is missing.
