"""T6 (REQ-2): apply the coordinate ALTER to the REAL application store.

This runs the verified idempotent migration (iris_ffi._PythonFallbackEngine
_run_migrations) against data/memory.db — the configured app store (resolved
via backend.memory.config.resolve_memory_store_path). T6-PRE backup confirmed
at C:\\Users\\midas\\AppData\\Local\\Temp\\opencode\\memory_backups\\memory.db.bak_20260806_125348
before running.

Effects (verified by test_der_chain_landing + test_chain_coordinate_store_contract):
- memory_chain gains coordinate columns (chain_id, coords_from, coords_to,
  nbl_outcome, insight, file_path, landmark_id, stale, mediator,
  mediator_source) — IDEMPOTENT, preserving the 1825 legacy rows with null coords.
- orphan memory_chain_v2 dropped.
- decoy backend/data/memory.db and .mcm/coordinates.db are NOT touched (AC5 guard).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.chdir(Path(__file__).resolve().parent.parent)

from backend.memory.config import resolve_memory_store_path


def main() -> int:
    db_path = resolve_memory_store_path()
    print("target store:", db_path)
    # The engine migration forbids .mcm/ and backend/data/ — assert we're
    # hitting the real app store before doing anything.
    p = str(db_path).replace("\\", "/")
    assert ".mcm/" not in p and "backend/data/" not in p, f"REFUSED wrong store: {p}"

    import sqlite3

    before = sqlite3.connect(db_path).execute(
        "SELECT COUNT(*) FROM memory_chain"
    ).fetchone()[0]
    print("memory_chain rows BEFORE:", before)

    from backend.gateway.iris_ffi import _PythonFallbackEngine

    eng = _PythonFallbackEngine(db_path=str(db_path), key_hex="00" * 32)
    eng.shutdown()

    con = sqlite3.connect(db_path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(memory_chain)")}
    after = con.execute("SELECT COUNT(*) FROM memory_chain").fetchone()[0]
    v2 = con.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='memory_chain_v2'"
    ).fetchone()[0]
    null_coords = con.execute(
        "SELECT COUNT(*) FROM memory_chain WHERE coords_from IS NULL "
        "AND coords_to IS NULL"
    ).fetchone()[0]
    con.close()

    print("has coords_from:", "coords_from" in cols)
    print("has mediator:", "mediator" in cols)
    print("memory_chain rows AFTER:", after)
    print("memory_chain_v2 present:", v2 == 1)
    print("legacy rows with null coords:", null_coords)

    ok = (
        "coords_from" in cols
        and "mediator" in cols
        and after == before == 1825
        and v2 == 0
        and null_coords == 1825
    )
    print("T6_APPLIED_AND_PRESERVED" if ok else "T6_APPLY_FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
