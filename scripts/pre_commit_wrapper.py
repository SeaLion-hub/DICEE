"""Git pre-commit hook wrapper: avoid pre-commit's patch-stash conflicting with ruff --fix.

pre-commit clears unstaged changes by saving a patch, running hooks, then git apply. When
ruff reformats a file, the patch often fails to re-apply ("Stashed changes conflicted with
hook auto-fixes"). Running `git stash push --keep-index` first leaves only the index in the
working tree, so hook-impl skips that path and ruff fixes apply cleanly. We then stash pop
to restore your uncommitted edits.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_STASH_MSG = "pre-commit-wrapper: keep-index"


def _git(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _repo_root() -> Path:
    p = _git("rev-parse", "--show-toplevel")
    if p.returncode != 0 or not p.stdout.strip():
        raise RuntimeError("git rev-parse --show-toplevel failed")
    return Path(p.stdout.strip())


def _unstaged_paths() -> list[str]:
    p = _git("diff", "--name-only")
    if p.returncode != 0:
        return []
    return [line.strip() for line in p.stdout.splitlines() if line.strip()]


def _run_hook_impl(repo: Path, hook_dir: Path) -> int:
    hook_impl = [
        sys.executable,
        "-m",
        "pre_commit",
        "hook-impl",
        "--config=.pre-commit-config.yaml",
        "--hook-type=pre-commit",
        "--hook-dir",
        str(hook_dir),
        "--",
        *sys.argv[1:],
    ]
    return subprocess.run(hook_impl, cwd=repo).returncode


def _print_hook_failure_hint() -> None:
    print(
        "\n".join(
            [
                "",
                "=" * 72,
                "pre-commit: 위쪽 로그에서 실패한 훅 이름(예: black, ruff, mypy)을 확인하세요.",
                "",
                "자주 있는 경우:",
                "  - check mixed stage: app/tests의 .py가 일부만 스테이징됨 → 전부 git add 하거나",
                "    SKIP=check-mixed-stage-python git commit ... (PowerShell: $env:SKIP='check-mixed-stage-python')",
                "  - black/ruff: 포맷/린트 수정 후 파일을 다시 스테이징 (git add) 후 커밋",
                "  - mypy: 타입 오류 수정",
                "",
                "같은 검사를 로컬에서:  pre-commit run --all-files",
                "=" * 72,
                "",
            ]
        ),
        file=sys.stderr,
    )


def main() -> int:
    try:
        repo = _repo_root()
    except RuntimeError:
        print(
            "pre-commit 래퍼: Git 저장소 루트를 찾을 수 없습니다 "
            "(`git rev-parse --show-toplevel` 실패). .git이 있는 폴더에서 커밋하세요.",
            file=sys.stderr,
        )
        return 1

    os.chdir(repo)
    hook_dir = repo / ".git" / "hooks"

    unstaged = _unstaged_paths()
    auto_stashed = False
    if unstaged:
        stash = _git(
            "stash",
            "push",
            "--keep-index",
            "-m",
            _STASH_MSG,
        )
        if stash.returncode != 0:
            detail = (stash.stderr or stash.stdout or "").strip()
            print(
                "\n".join(
                    [
                        "",
                        "=" * 72,
                        "pre-commit 래퍼: `git stash push --keep-index`가 실패했습니다.",
                        "미스테이징 변경을 잠시 치우지 못해 커밋을 계속할 수 없습니다.",
                        "",
                        *(["git 메시지:", detail, ""] if detail else []),
                        "조치: 작업 트리 충돌/lock을 해소한 뒤 다시 커밋하거나,",
                        "        기본 훅만 쓰려면 `pre-commit install` 후 래퍼 설치 스크립트는 생략.",
                        "=" * 72,
                        "",
                    ]
                ),
                file=sys.stderr,
            )
            return 1
        auto_stashed = True

    ret = 1
    try:
        ret = _run_hook_impl(repo, hook_dir)
        if ret != 0:
            _print_hook_failure_hint()
    finally:
        if auto_stashed:
            pop = subprocess.run(["git", "stash", "pop"], cwd=repo)
            if pop.returncode != 0:
                print(
                    "pre-commit wrapper: `git stash pop` failed (conflicts?). "
                    "Resolve files, then `git add` as needed. "
                    "If the stash is unwanted: `git stash list` then `git stash drop`.\n"
                    f"Stash message should contain: {_STASH_MSG!r}",
                    file=sys.stderr,
                )
                if ret == 0:
                    ret = 1

    return ret


if __name__ == "__main__":
    raise SystemExit(main())
