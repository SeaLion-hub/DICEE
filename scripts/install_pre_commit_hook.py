"""Install .git/hooks/pre-commit to run scripts/pre_commit_wrapper.py (keep-index stash).

Run once per clone (and again after `pre-commit install -f` if that overwrote the hook):

    python scripts/install_pre_commit_hook.py
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    hook_path = root / ".git" / "hooks" / "pre-commit"
    if not hook_path.parent.is_dir():
        print(".git/hooks missing; not a git checkout?", file=sys.stderr)
        return 1

    py = Path(sys.executable).resolve()
    py_sh = str(py).replace("\\", "/")

    body = f"""#!/bin/sh
# Installed by scripts/install_pre_commit_hook.py (keep-index wrapper for pre-commit).
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT" || exit 1
export PYTHONUTF8=1
exec "{py_sh}" "$ROOT/scripts/pre_commit_wrapper.py" "$@"
"""
    hook_path.write_text(body, newline="\n")
    mode = hook_path.stat().st_mode
    hook_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Wrote {hook_path}")
    print("If you later run `pre-commit install -f`, run this script again to restore the wrapper.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
