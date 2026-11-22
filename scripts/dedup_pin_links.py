"""Remove the copied rows in mycelium_pin_links (offline, human-run).

Measured 2026-11-22: 56,325 rows held only 301 distinct links - `PinStore.link`
inserted on every call (one DER link 9,029 times). `link` now writes a link only once
and DER links carry their session (der_links._node_id); this removes the copies already
written, keeping the NEWEST row of each link (recall orders newest first). Nothing that
is a distinct link is removed. Idempotent.

    python scripts/dedup_pin_links.py --dry-run   # counts only
    python scripts/dedup_pin_links.py             # remove the copies

Writes go through db.app_write + app_flush (the one writer), inside pin_store.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._app_store import app_store_path  # noqa: E402
from backend.memory.db import open_encrypted_memory  # noqa: E402
from backend.memory.pin_store import PinStore  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="count only, remove nothing")
    args = ap.parse_args()
    conn = open_encrypted_memory(app_store_path(), b"")
    try:
        out = PinStore(conn=conn).remove_duplicate_links(dry_run=args.dry_run)
        if not args.dry_run:
            out["left"] = int(conn.execute("SELECT COUNT(*) FROM mycelium_pin_links").fetchone()[0])
    finally:
        conn.close()
    print(("would remove" if args.dry_run else "removed"), out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
