# Runbook: Redis Scheduler Recovery

## 목적

Redis 기반 트리거 락·스케줄·크롤 큐 이상 시 복구 절차. 락 정리·스케줄 재정합·stuck inflight 복구를 수행한다.

## 트리거

- Redis 연결 실패·타임아웃 반복
- 트리거 락 TTL 만료 전 해제 실패로 크롤 미실행
- stuck inflight(장시간 실행 중) 작업 다수 발생
- 신선도 SLO(95% due+15분 내 완료) 위반

## 담당

- **Data Platform**: Redis·Celery Beat·워커 운영
- **SRE**: Redis 인스턴스·네트워크 점검

## 기본 절차

1. Redis PING·연결 상태 확인. `/ready` 엔드포인트에서 redis_trigger_lock 상태 확인.
2. 트리거 락 키 패턴 점검. 만료된 락은 자동 해제 대기; 비정상 장기 보유 시 키 삭제 검토(한 번에 소량만).
3. Celery 워커·Beat 프로세스 상태 확인. 재시작 시 큐 깊이·재시도 정책에 따른 부하 고려.
4. stuck inflight 재처리 배치(문서화된 경우): 실행 주기·한도 확인. 배치가 오래 실행 중인 작업을 error_feed/재큐로 이관하는지 확인.
5. 복구 후 신선도 SLO·크롤 실행 로그 재확인.
