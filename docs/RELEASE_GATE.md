# RELEASE GATE (P0/P1) - DICEE-1

목적: "문제가 0개"가 아니라, 운영 리스크 허용선 이하인지로 머지/배포를 결정한다.

## 1) 종료 조건 (Stop Rule)

아래 4개를 모두 만족하면 종료한다.

- P0 항목 100% 완료
- P1 항목 90% 이상 완료 + 미완료 항목은 리스크 수용(Owner/기한 명시)
- 필수 검증 커맨드 통과
- Go/No-Go 승인 로그 기록

## 2) P0 체크리스트 (Release Blocker, 하나라도 미충족이면 No-Go)

- [ ] 인증/세션 보안 경로가 장애 시 의도대로 fail-closed 동작한다.
- [ ] OAuth redirect_uri allowlist가 production에서 강제된다.
- [ ] 내부 트리거(/internal/trigger-crawl) 부분 실패를 성공(200)으로 숨기지 않는다.
- [ ] idempotency 실패 시 중복 실행 폭주를 허용하지 않는다.
- [ ] 스토리지 업로드 실패가 무음 데이터 유실로 끝나지 않는다.
- [ ] 크롤러 반환 타입 계약(ScrapeResult)이 모든 예외 경로에서 일관된다.
- [ ] run/task idempotency가 재시도 시 결정적으로 유지된다(랜덤 대체 금지).
- [ ] readiness가 보안 핵심 의존성 저하를 정상으로 보고하지 않는다.
- [ ] P0 수정마다 회귀 테스트가 추가되어 재발을 방지한다.

## 3) P1 체크리스트 (High, 배포 전 정리 권장)

- [ ] content_hash가 실제 변경 요소(첨부/이미지 포함)를 반영한다.
- [ ] 비동기 재시도(backoff)가 워커 처리량을 과도하게 블로킹하지 않는다.
- [ ] X-Forwarded-For private/invalid 처리 정책이 스푸핑 우회 없이 일관된다.
- [ ] S3 저장 시 암호화(KMS/SSE) 정책이 코드 또는 버킷 정책으로 강제된다.
- [ ] production에서 s3 설정 누락 시 local fallback 대신 fail-fast 한다.
- [ ] 운영 문서(.env.example, DEPLOYMENT, ADR)와 실제 코드 정책이 일치한다.
- [ ] 관측성 지표가 실패를 "성공처럼" 보이게 만들지 않는다.
- [ ] 에러 코드/응답 계약(4xx/5xx)이 재시도 전략과 일치한다.

## 4) 필수 검증 커맨드 (증빙)

- `pytest -q`
- `ruff check app tests`
- `mypy app`
- `alembic upgrade head` (staging DB. staging DB 설정·연결은 [DEPLOYMENT](DEPLOYMENT.md) "로컬 개발 참고"·Railway Variables 참고.)
- **스모크 테스트**: 아래 엔드포인트 케이스로 핵심 경로가 기동 후 정상/장애 시 의도대로 동작하는지 최소 검증.
- `POST /internal/trigger-crawl` 성공/부분실패/전체실패 케이스
- `POST /v1/auth/google`, `/v1/auth/refresh`, `/v1/auth/logout` 정상/장애 케이스
- `/ready`, `/health`, `/internal/metrics` 접근 제어 케이스

## 5) Go/No-Go 판정 템플릿

- Decision: `Go` | `No-Go`
- Date: `YYYY-MM-DD`
- Reviewer: `name`
- P0: `N/N pass`
- P1: `N/N pass`
- 남은 리스크(수용): `항목 / 영향 / Owner / 기한`
- 롤백 계획 확인: `Yes | No`

## 6) 운영 규칙

- "이슈가 더 나오지 않을 때까지" 반복하지 않는다.
- 컷라인 재협상은 배포 전 1회만 허용한다.
- 미완료 P1은 반드시 이슈 트래커 티켓 번호로 연결한다.

---

## 참고

| 문서 | 용도 |
|------|------|
| [ROADMAP](ROADMAP.md) | 현재 마일스톤·전략. 배포 전 단계 정합성 확인. |
| [DEPLOYMENT](DEPLOYMENT.md) | Railway·환경변수·staging DB·Go-Live 검증. |
