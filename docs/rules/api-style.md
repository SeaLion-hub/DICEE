# API·구조·Auth 스타일 가이드

작업 시 API·진입점·Auth 관련 코드를 건드릴 때 참고할 매뉴얼. 상세는 [CAUTIONS](../CAUTIONS.md)와 [ROADMAP](../ROADMAP.md) 참고.

---

## 진입점·구조

- **진입점**: `app.main:app` 고정. DEPLOYMENT Start Command와 일치. 루트에 `app/` 패키지.
- **폴더**: `api/`, `core/`, `services/` 등 ROADMAP 1단계 계층형 디렉터리 유지. 새 폴더는 `app/` 안에만 추가.
- **설정**: URL·키워드·선택자는 코드에 하드코딩하지 말고 config·환경변수·DB로 분리.

---

## API

- 공개 API는 **`/v1/` prefix**. 기존 필드 삭제·이름 변경 금지. 추가만 하거나 `/v2/`로.
- 새 환경변수 사용 시 **DEPLOYMENT 표 + .env.example** 동시 갱신. 값은 로컬 .env·Railway Variables에만.

---

## Auth·CORS

- OAuth 핸드쉐이크는 **2단계에서** 확정(프론트가 code를 백으로 전달 → 백이 JWT 발급 → body JSON vs HttpOnly Cookie). CORS·Credentials를 그에 맞춰 설계.
- 토큰 무효화(로그아웃): DB(Refresh 버전 증가) 선행 → Redis(Blocklist 등록). Redis 실패 시 예외 발생·클라이언트 재시도 가능.
- 6단계 연동 전 Railway Variables에 **ALLOWED_ORIGINS**(Vercel URL) 설정.
