#!/usr/bin/env python3
"""Print Alembic upgrade order from base to head (reversed iterate_revisions).

Used to verify dual-root merge ordering; run from repo root:
  python scripts/dump_alembic_upgrade_order.py
"""

from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory


def main() -> None:
    cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(cfg)
    revs = list(script.iterate_revisions(script.get_heads()[0], None, implicit_base=True))
    order = list(reversed(revs))
    for i, s in enumerate(order):
        print(f"{i:2} {s.revision}")


if __name__ == "__main__":
    main()
