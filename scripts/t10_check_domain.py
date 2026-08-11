"""T10 verify: does the real app store's caducean_trajectories lack domain?"""
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.chdir(Path(__file__).resolve().parent.parent)

from backend.memory.config import resolve_memory_store_path


def main():
    p = resolve_memory_store_path()
    con = sqlite3.connect(p)
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    if "caducean_trajectories" not in tables:
        print("store:", p)
        print("caducean_trajectories: ABSENT (no migration needed)")
        return
    cols = [r[1] for r in con.execute("PRAGMA table_info(caducean_trajectories)")]
    con.close()
    print("store:", p)
    print("cols:", cols)
    print("has domain:", "domain" in cols)


if __name__ == "__main__":
    main()
