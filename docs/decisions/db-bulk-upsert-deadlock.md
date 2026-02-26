# DB Bulk Upsert 데드락(Deadlock) 방지 전략

## 배경 (Context)
DICEE는 크롤링 속도 제한을 준수하면서도 빠르게 데이터를 수집하기 위해 다수의 Celery 워커를 병렬로 실행합니다. 수집된 데이터는 `INSERT ... ON CONFLICT DO UPDATE` 구문을 통해 PostgreSQL에 Bulk Upsert 됩니다. 
하지만 여러 워커가 무작위 순서로 나열된 공지사항 배열을 동시에 DB에 밀어넣을 때, 교집합 데이터가 존재하면 워커 간에 행 수준 잠금(Row-level Lock)을 획득하는 순서가 엇갈려 필연적으로 **순환 대기(데드락, Deadlock)**가 발생하고 트랜잭션이 강제 롤백되는 치명적인 문제가 있었습니다.

## 결정 (Decision)
PostgreSQL 내에서 `CTE(WITH)` 구문으로 정렬하는 방식 대신, **파이썬 애플리케이션 레벨(SQLAlchemy ORM)에서 DB에 쿼리를 날리기 직전에 리스트를 복합 유니크 키(`college_id`, `external_id`) 기준으로 오름차순 정렬(`sorted()`)** 하도록 강제했습니다.

## 결과 및 장점 (Consequences)
1. **데드락 원천 차단:** 모든 병렬 워커가 항상 동일한 방향(ID가 작은 것부터 큰 순서)으로 배타적 잠금(Exclusive Lock)을 획득하게 되어 순환 참조가 수학적으로 불가능해집니다.
2. **가독성 및 유지보수성:** 복잡한 Raw SQL을 작성할 필요 없이, 기존 SQLAlchemy 2.0 쿼리 구조를 그대로 유지하면서 단 4줄의 정렬 코드만으로 문제를 완벽히 해결했습니다.