"""
아키텍처 계층 import 규칙 검사.

단일 소스: 계층/의존성 규칙은 import-linter(pyproject.toml [tool.importlinter])에서 정의.
이 테스트는 lint-imports CLI 실행을 위임해, 규칙 드리프트 없이 동일 검사 수행.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_architecture_import_rules_via_import_linter() -> None:
    """import-linter를 실행해 API/서비스 계층 규칙(api→repositories 금지, services→schemas 금지) 검사."""
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["lint-imports"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=root,
    )
    assert result.returncode == 0, (
        f"lint-imports failed (exit {result.returncode}).\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
