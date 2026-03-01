# ADR: crawl_runs 진행률·체크포인트 (processed_count, checkpointed_at)

**상태**: 채택  
**배경**: 진행률 가시성 및 향후 재개(Resume) 설계의 기반으로, 크롤 실행 중 "지금까지 처리한 건수"와 "마지막 갱신 시각"을 저장한다. Resume 전략(이어하기)은 순서 보장 방식과 함께 별도 ADR로 분리한다.

---

## 결정

1. **필드**: `crawl_runs`에 다음만 추가한다.
   - `processed_count` (int, default 0): 지금까지 처리한 공지/링크 수.
   - `checkpointed_at` (datetime with timezone, nullable): 마지막 체크포인트 갱신 시각.
   - `last_processed_external_id`는 이 단계에서 도입하지 않는다. 현재 크롤은 병렬/완료순 처리로 순서가 비결정적이어서 Resume 키로 쓰기엔 위험하다.

2. **갱신 시점**: 체크포인트는 **청크 upsert와 동일 트랜잭션·같은 세션**에서 갱신한다. 즉, 청크 upsert 직후 같은 세션으로 `update_crawl_run_checkpoint_sync(session, run_id, processed_count, checkpointed_at)` 호출 후 `session.commit()`. 분리 커밋하면 진행률과 실데이터가 어긋날 수 있다.

3. **리포지토리**: `update_crawl_run_checkpoint_sync(session, run_id, processed_count, checkpointed_at)`를 제공하며, 내부적으로 `update_crawl_run_sync`의 해당 인자만 설정한다. `create_or_update_crawl_run_sync`로 run 재사용 시 `processed_count`·`checkpointed_at`는 0/None으로 초기화한다.

---

## 적용 위치

- `app/models/crawl_run.py`: `processed_count`, `checkpointed_at` 컬럼.
- `app/repositories/crawl_run_repository.py`: `update_crawl_run_checkpoint_sync`, `update_crawl_run_sync`/`create_or_update_crawl_run_sync` 인자 확장.
- `app/services/crawl_service.py`: `_finalize_chunk_sync` 내 청크 upsert 직후, 같은 트랜잭션에서 체크포인트 갱신 후 commit.
- Alembic: `009_crawl_runs_processed_checkpointed.py`.
