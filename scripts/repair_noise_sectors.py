"""Fold the noise child sectors back into their parents (offline, human-run).

Found 2026-11-22 on the live store: child sectors named after path segments of eval
prompts (appdata, local, evals, iris), one task repeated across sessions (https: 25
sessions, 1 task text), words of every root (look, project, name, search, year), and
grandchildren that repeat their parent's word (data/https/https). The birth rule now
refuses them (backend/memory/mycelium/sectors.py `term_can_name_child`); this script
applies the SAME rule to the rows already written.

A fold is the dissolve path the lifecycle already uses: status `dissolved`, `alias_of`
= the parent, so an old address still resolves. No row is deleted. Idempotent.

    python scripts/repair_noise_sectors.py --dry-run   # the plan only
    python scripts/repair_noise_sectors.py             # fold

Writes go through db.app_write + app_flush (the one writer), inside sectors.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._app_store import app_store_path  # noqa: E402
from backend.memory.db import open_encrypted_memory  # noqa: E402
from backend.memory.mycelium.sectors import fold_noise_children  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    args = ap.parse_args()
    conn = open_encrypted_memory(app_store_path(), b"")
    try:
        plan = fold_noise_children(conn, dry_run=args.dry_run)
    finally:
        conn.close()
    for row in plan:
        print(f"{row['sector']:28} {row['status']:9} -> {row['parent']:18} "
              f"labels={row['labels']:3} roots={row['roots']}  {row['why']}")
    print(f"{'would fold' if args.dry_run else 'folded'}: {len(plan)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
