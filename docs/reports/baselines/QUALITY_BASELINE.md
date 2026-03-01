# Quality Baseline

This document defines the current quality baseline and how to verify it locally and in CI.

## Baseline Metrics

| Item | Command | Baseline |
|---|---|---|
| Pytest | `pytest tests -q --tb=no` | 167 passed, 3 skipped |
| Coverage | `pytest tests --cov=app --cov-fail-under=50` | CI threshold 50%; goal 80%. |
| Mypy | `mypy app` | 0 errors |
| Architecture guard | `pytest -q tests/test_architecture_imports.py` (위임: `lint-imports`) | pass |
| Ruff | `ruff check app tests` | pass |

## Local Verification

```bash
pytest tests -q --tb=no
mypy app
ruff check app tests
pytest -q tests/test_architecture_imports.py
```

## Notes

- **Architecture (single source of truth)**: 계층/import 규칙의 **단일 진실원**은 `pyproject.toml` [tool.importlinter] 뿐이다. `tests/test_architecture_imports.py`는 `lint-imports` CLI 실행만 위임하며, AST로 import 규칙을 중복 검사하지 않는다. 규칙 추가·변경은 pyproject.toml만 수정하고, 테스트는 그대로 두면 된다.
- CI must pass `ruff`, `mypy`, architecture guard, and `pytest` before merge.
- Per-module strict typing should be introduced incrementally with module-specific flags.
- Do not use `strict = true` inside mypy overrides.
