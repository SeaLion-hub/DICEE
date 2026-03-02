# Runbook: Release Rollback

## 목적

배포 후 SLO·큐·DLQ 악화 시 롤백 트리거에 따른 판단 및 이전 버전으로 롤백 수행. 롤백 조건·담당·기본 절차를 정의한다.

## 트리거 (롤백 트리거 — 아무거나 1개 충족 시)

- **Critical burn-rate** 상태 **10분** 지속  
  - burn-rate > 14.4를 **5m**와 **1h**에서 동시 만족
- **queue_depth** > 7일 기준선의 **3배**가 **30분** 지속
- **DLQ 유입률** > **1%**가 **30분** 지속
- **신선도 SLO** **90% 미만**이 **30분** 지속  
  - 95% 작업이 due+15분 내 완료 목표 대비

수치는 단일 소스(docs/decisions/slo-rollback-thresholds.md)에서 관리 시 해당 문서를 우선 참조.

## 담당

- **SRE**: 롤백 실행·모니터링 복구 확인
- **Backend**: 롤백 후 원인 분석·핫픽스

## 기본 절차

1. 위 트리거 충족 여부 재확인(지속 시간·임계치). 오탐(저트래픽 등)이면 알럿만 정리하고 관찰.
2. 롤백 결정 시: 배포 플랫폼(Railway 등)에서 이전 성공 배포로 롤백 실행. DB 마이그레이션 롤백 필요 시 별도 절차 수행.
3. 롤백 후: API 가용성·지연·크롤 성공률·신선도·queue_depth·DLQ 유입률 재확인.
4. 원인 분석: Sentry release·로그·변경 이력으로 원인 파악. 재배포 전 수정·테스트 완료 후 진행.
5. Runbook 링크: [api-error-budget.md](api-error-budget.md), [crawler-retry-dlq.md](crawler-retry-dlq.md), [redis-scheduler-recovery.md](redis-scheduler-recovery.md).
