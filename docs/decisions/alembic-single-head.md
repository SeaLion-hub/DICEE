# Alembic 단일 head 정책

## 상태

수용 (2026-02-27), 보강 (2026-03-28)

## 배경

P0/Dev4 등 브랜치 머지로 인해 두 개의 마이그레이션 체인(001→…→006, v7_001→…→006_schema_contract_fix)이 공존했고, `alembic upgrade head` 실행 시 "Multiple head revisions" 오류로 배포가 실패했다.

빈 데이터베이스에서 head까지 올릴 때 Alembic은 두 base를 모두 만족해야 하므로 **v7 체인이 먼저 적용된 뒤 레거시 001→006이 실행**될 수 있다. 이 경우 레거시 `001_initial`이 이미 존재하는 `colleges` 등을 다시 만들려 하면 `relation already exists`로 실패한다.

## 결정

- **단일 head 유지**: 저장소에는 항상 **하나의** Alembic head만 존재한다(현재 head는 `alembic heads`로 확인; 예: `012_notice_embedding`).
- **머지 리비전**: 두 체인을 합치는 `007_merge_heads`가 필요하다. 이후 새 마이그레이션은 **현재 head**를 `down_revision`으로 두고 선형으로 이어간다.
- **레거시 체인 no-op (B1)**: `001`~`006`의 `upgrade()`는 `app.legacy_alembic_guard.v7_base_schema_present`로 **이미 v7 스키마(colleges.id가 UUID)면 DDL을 건너뛴다.** 빈 DB에서 `upgrade head`가 재현 가능하게 성공하도록 한다.
- **배포**: 배포 브랜치에 `007_merge_heads.py` 및 이후 선형 리비전이 포함되어야 한다.
- **CI**: `.github/workflows/ci.yml`에서 `alembic heads`가 정확히 1개인지 검사하고, `alembic upgrade head` 직후 **`alembic check`**로 ORM 메타데이터와 DB 스키마 드리프트를 검사한다.

## 새 마이그레이션 작성 시

1. `alembic revision -m "설명"` 생성 후 `down_revision`을 **현재 head 리비전 ID**로 설정한다.
2. `alembic heads`로 head가 하나인지 확인한다.
3. 두 체인에서 동시에 새 리비전을 만들지 않는다. 먼저 머지 후 단일 head에서만 분기한다.

## 참고

- [DEPLOYMENT.md](../DEPLOYMENT.md) — Alembic·pgvector·`stamp` 시나리오
- `alembic/versions/007_merge_heads.py` — 머지 리비전(스키마 변경 없음)
- `app/legacy_alembic_guard.py` — v7 적용 후 레거시 001→006 스킵
- `scripts/dump_alembic_upgrade_order.py` — base→head 적용 순서 덤프(디버깅)

## Quality gates

- CI: `ruff` / `mypy app` / `alembic heads`(1개) / `alembic upgrade head` / **`alembic check`** / `pytest`
