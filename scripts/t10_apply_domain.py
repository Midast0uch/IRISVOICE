"""T10 (REQ-12): apply the domain-column migration to the real app store.

Runs CaduceanTrajectoryRecorder._ensure_table against the configured store
(resolve_memory_store_path), which idempotently adds `domain` to a pre-domain
caducean_trajectories. T6-PRE backup already covers the store.
"""
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.chdir(Path(__file__).resolve().parent.parent)

from backend.memory.config import resolve_memory_store_path


def main() -> int:
    from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder

    db_path = resolve_memory_store_path()
    print("target store:", db_path)
    p = str(db_path).replace("\\", "/")
    assert ".mcm/" not in p and "backend/data/" not in p, f"REFUSED wrong store: {p}"

    con = sqlite3.connect(db_path)
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    had_table = "caducean_trajectories" in tables
    before = None
    if had_table:
        before = {r[1] for r in con.execute("PRAGMA table_info(caducean_trajectories)")}
    con.close()

    CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(db_path))

    con = sqlite3.connect(db_path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(caducean_trajectories)")}
    con.close()
    print("before had domain:", "domain" in (before or set()))
    print("after has domain:", "domain" in cols)
    ok = "domain" in cols
    print("T10_APPLIED" if ok else "T10_FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
