# Runbook: API Error Budget

## 목적

API 가용성·지연 SLO 초과 시 에러 예산 소진 대응 절차. SLO 복구 및 원인 조사·개선 조치를 수행한다.

## 트리거

- API 가용성 SLO(99.5%, 30일) 위반 알럿
- API 지연 SLO(p95 < 1.5s) 위반 알럿
- Error budget burn-rate 알럿(Critical/Warning) 수신

## 담당

- **SRE**: 알럿 수신·초기 판단·Runbook 실행
- **Backend**: API/Schema/DI 원인 분석·배포·핫픽스

## 기본 절차

1. 알럿 확인: burn-rate 구간(5m/1h, 30m/6h), 최소 트래픽 조건(300 req/5m 이상) 충족 여부 확인.
2. 대시보드에서 요청량·에러율·지연 분포 확인. 이상 구간(엔드포인트·시간대) 식별.
3. 로그·Sentry에서 해당 구간 에러·예외 패턴 확인. trace_id/request_id로 추적.
4. 원인에 따라: 배포 롤백(릴리스 문제 시), 스케일 업/아웃, DB/캐시 점검, 코드 핫픽스 등 결정.
5. 조치 후 SLO·burn-rate 재확인. 필요 시 [release-rollback.md](release-rollback.md) 참조.
