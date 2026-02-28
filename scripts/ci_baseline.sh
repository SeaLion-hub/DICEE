#!/usr/bin/env bash
# 로컬에서 품질 기준 수치를 뽑을 때 사용.
# 사용법: 프로젝트 루트에서 ./scripts/ci_baseline.sh
set -e
echo "=== Pytest ==="
pytest tests -q --tb=no 2>&1 || true
echo ""
echo "=== Mypy app ==="
mypy app 2>&1 || true
echo ""
echo "=== Mypy --strict app (참고용) ==="
mypy --strict app 2>&1 || true
