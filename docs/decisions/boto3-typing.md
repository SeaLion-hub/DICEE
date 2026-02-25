# boto3 타입 검사 규칙

## 결정

- **boto3 타입**: 팀 규칙은 **한 가지만** 사용한다.
- **채택**: **types-boto3** 패키지 사용 (옵션 A).
  - `requirements-dev.txt`에 `types-boto3` 추가.
  - mypy가 boto3 스텁을 사용하므로 `app.core.storage` 등 boto3 사용 모듈에서 `# type: ignore[import-not-found]` 또는 전역 `import-not-found` disable을 쓰지 않는다.
- **미채택**: 스텁 없이 import 라인에만 `# type: ignore[import-not-found]` 최소 범위 적용(옵션 B)은 사용하지 않는다.
- 한 번 결정 후 동일 방식만 사용(혼용 금지).

## 참고

- 계획: 타입·Ruff·crawl_runs 개선 — §4.1 boto3 팀 규칙.
