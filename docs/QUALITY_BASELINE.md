# Quality Baseline

This document defines the current quality baseline and how to verify it locally and in CI.

## Baseline Metrics

| Item | Command | Baseline |
|---|---|---|
| Pytest | `pytest tests -q --tb=no` | 130 passed, 3 skipped |
| Mypy | `mypy app` | 0 errors |
| Architecture guard | `pytest -q tests/test_architecture_imports.py` | pass |
| Ruff | `ruff check app tests` | pass |

## Local Verification

```bash
pytest tests -q --tb=no
mypy app
ruff check app tests
pytest -q tests/test_architecture_imports.py
```

## Notes

- CI must pass `ruff`, `mypy`, architecture guard, and `pytest` before merge.
- Per-module strict typing should be introduced incrementally with module-specific flags.
- Do not use `strict = true` inside mypy overrides.
