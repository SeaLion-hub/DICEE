# Alembic 단일 head 정책

## 상태

수용 (2026-02-27)

## 배경

P0/Dev4 등 브랜치 머지로 인해 두 개의 마이그레이션 체인(001→…→006, v7_001→…→006_schema_contract_fix)이 공존했고, `alembic upgrade head` 실행 시 "Multiple head revisions" 오류로 배포가 실패했다.

## 결정

- **단일 head 유지**: 저장소에는 항상 **하나의** Alembic head만 존재한다.
- **머지 리비전**: 두 체인을 합치는 `007_merge_heads`를 유일한 head로 둔다. 이후 새 마이그레이션은 `down_revision = "007_merge_heads"`(또는 그 다음 최신 리비전)로 선형 이력을 이어간다.
- **배포**: 배포에 사용하는 브랜치에는 `alembic/versions/007_merge_heads.py`가 **반드시 포함**되어야 한다. 포함되지 않으면 `alembic upgrade head`가 실패한다.
- **CI**: `.github/workflows/ci.yml`에서 `alembic heads` 결과가 정확히 1개인지 검사한다. 다중 head가 생기면 PR/푸시가 실패한다.

## 새 마이그레이션 작성 시

1. `alembic revision -m "설명"` 생성 후, 생성된 파일에서 `down_revision`을 **현재 head 리비전 ID**로 설정한다.
2. `alembic heads`로 현재 head가 하나인지 확인한다.
3. 두 체인에서 동시에 새 리비전을 만들지 않는다. 먼저 머지 리비전으로 합친 뒤, 그 head에서만 분기한다.

## 참고

- DEPLOYMENT.md "빌드·실행 설정" — 배포 브랜치 요구사항
- `alembic/versions/007_merge_heads.py` — 머지 리비전(스키마 변경 없음)
