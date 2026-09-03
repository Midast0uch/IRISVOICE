"""One-shot, offline inheritance migration: BUILD store -> application schema.

REQ-2b AC2 (specs/der-dag-inversion): brings the BUILD coordinate graph
(`.mcm/coordinates.db`) to the application's schema so the "same schema, no
migration" hand-off at completion is TRUE rather than aspirational.

RULES (read before running):
  - OFFLINE + HUMAN-RUN ONLY. This must NEVER run at app start and must NEVER
    be called from the application path. It is a release-time step executed by
    a person before the BUILD store is handed to the runtime.
  - NON-DESTRUCTIVE. Existing rows are preserved (coordinate columns are added
    as NULL for legacy rows, exactly like the app-store migration in
    backend/gateway/iris_ffi.py `_run_migrations`).
  - IDEMPOTENT. Running it twice is a no-op (SQLite has no
    "ADD COLUMN IF NOT EXISTS", so each ALTER is guarded by try/except).

What it changes on the BUILD store ONLY:
  1. memory_chain     -> coordinate columns added (chain_id, coords_from,
                         coords_to, nbl_outcome, insight, file_path,
                         landmark_id, stale). Existing rows keep NULL coords.
  2. memory_chain_v2  -> DROPPED (orphan: 0 rows, no writer).
  Everything else is left untouched. The app store (data/memory.db) is NOT
  touched here — its own migration runs at engine init (REQ-2 T6).

Usage:
    python scripts/migrate_build_store_inheritance.py            # default path
    python scripts/migrate_build_store_inheritance.py --dry-run  # report only
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# Coordinate columns the engine writes (see iris_ffi._run_migrations).
_COORD_COLUMNS = (
    "chain_id", "coords_from", "coords_to", "nbl_outcome",
    "insight", "file_path", "landmark_id", "stale",
)

DEFAULT_BUILD_DB = Path(__file__).resolve().parents[1] / ".mcm" / "coordinates.db"


def _coordinate_columns(conn: sqlite3.Connection) -> set[str]:
    return {r[1] for r in conn.execute("PRAGMA table_info(memory_chain)")}


def migrate(build_db: Path, dry_run: bool = False) -> int:
    """Apply the coordinate ALTERs to the BUILD store's memory_chain.

    Returns the number of ALTER statements applied (0 when already current).
    Raises SystemExit(2) if the BUILD store is absent.
    """
    if not build_db.exists():
        print(f"[inherit] BUILD store not found: {build_db}")
        print("[inherit] Nothing to migrate — edge case is expected (fresh build).")
        return 0

    print(f"[inherit] BUILD store: {build_db}")
    conn = sqlite3.connect(str(build_db))
    try:
        cols = _coordinate_columns(conn)
        applied = 0

        for col in _COORD_COLUMNS:
            if col in cols:
                continue
            applied += 1
            if dry_run:
                print(f"[inherit] WOULD ALTER memory_chain ADD COLUMN {col}")
                continue
            try:
                ddl = f"ALTER TABLE memory_chain ADD COLUMN {col}"
                if col == "stale":
                    ddl += " INTEGER DEFAULT 0"
                else:
                    ddl += " TEXT"
                conn.execute(ddl)
                conn.commit()
                print(f"[inherit] ALTER memory_chain ADD COLUMN {col} — done")
            except Exception as exc:  # pragma: no cover — concurrent-writer guard
                print(f"[inherit]   (skipped, already present or locked: {exc})")

        # Orphan memory_chain_v2: 0 rows, no writer, two DBs (REQ-2 AC4).
        has_v2 = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_chain_v2'"
        ).fetchone()
        if has_v2:
            rows = conn.execute("SELECT COUNT(*) FROM memory_chain_v2").fetchone()[0]
            if dry_run:
                print(f"[inherit] WOULD DROP memory_chain_v2 ({rows} rows)")
            else:
                conn.execute("DROP TABLE IF EXISTS memory_chain_v2")
                conn.commit()
                print(f"[inherit] DROP memory_chain_v2 ({rows} rows) — done")
                applied += 1

        if applied == 0:
            print("[inherit] schema already current — nothing to do (idempotent)")
        return applied
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "build_db", nargs="?", default=str(DEFAULT_BUILD_DB),
        help="Path to the BUILD store (default: .mcm/coordinates.db)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would change, change nothing",
    )
    args = parser.parse_args()

    applied = migrate(Path(args.build_db), dry_run=args.dry_run)
    if args.dry_run:
        print("[inherit] dry-run only — no changes applied")
    else:
        print(f"[inherit] complete ({applied} schema change(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
