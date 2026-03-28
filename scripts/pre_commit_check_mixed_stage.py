"""Fail pre-commit early when app/tests *.py have both staged and unstaged changes.

Black/ruff --fix with partial staging makes pre-commit stash unstaged hunks; auto-fixes
can conflict and produce 'Stashed changes conflicted with hook auto-fixes'. Full-stage
those files or use SKIP=check-mixed-stage-python for intentional partial commits.
"""

from __future__ import annotations

import subprocess
import sys


def _git_lines(*args: str) -> list[str]:
    proc = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def main() -> int:
    unstaged = set(_git_lines("diff", "--name-only"))
    staged = set(_git_lines("diff", "--cached", "--name-only"))
    mixed = sorted(unstaged & staged)

    risky = [
        p
        for p in mixed
        if p.endswith(".py") and (p.startswith("app/") or p.startswith("tests/"))
    ]
    if not risky:
        return 0

    lines = [
        "",
        "=" * 72,
        "pre-commit: 같은 파일에 스테이징 + 미스테이징 변경이 같이 있습니다.",
        "black/ruff가 고치면 stash 충돌로 커밋이 실패할 수 있습니다.",
        "",
        "해결: 해당 파일 전체를 스테이징 (git add <파일>)",
        "의도적 부분 스테이징이면: SKIP=check-mixed-stage-python git commit ...",
        "",
        "대상 파일:",
        *[f"  - {p}" for p in risky],
        "=" * 72,
        "",
    ]
    print("\n".join(lines), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
