"""T6-PRE (SAFETY): copy data/memory.db to a timestamped backup OUTSIDE the
repo and verify the copy opens with the expected row counts.

Requirement (specs/der-dag-inversion/tasks.md T6-PRE): before ANY schema
change, copy `data/memory.db` to a timestamped backup OUTSIDE the repo and
verify the copy opens and returns the expected row counts (memory_chain = 1825
at time of writing). This database holds the user's real cross-conversation
memory. Record the backup path.
"""
import os
import shutil
import sqlite3
import time

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "memory.db"))
# OUTSIDE the repo — never inside C:\dev\IRISVOICE.
BACKUP_DIR = r"C:\Users\midas\AppData\Local\Temp\opencode\memory_backups"


def main() -> int:
    if not os.path.exists(SRC):
        print(f"SRC MISSING: {SRC}")
        return 1
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"memory.db.bak_{stamp}")
    # Copy the main db file + any WAL so the backup is crash-consistent.
    shutil.copy2(SRC, dst)
    wal = SRC + "-wal"
    if os.path.exists(wal):
        shutil.copy2(wal, dst + "-wal")
    shm = SRC + "-shm"
    if os.path.exists(shm):
        shutil.copy2(shm, dst + "-shm")

    # Verify the copy opens and returns expected row counts.
    con = sqlite3.connect(dst)
    cur = con.cursor()
    counts = {}
    for t in ("memory_chain", "memory_chain_v2"):
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            counts[t] = cur.fetchone()[0]
        except Exception as e:
            counts[t] = f"ERROR {e}"
    con.close()

    print(f"BACKUP: {dst}")
    print(f"counts: {counts}")
    ok = counts.get("memory_chain") == 1825
    print("VERIFIED" if ok else "COUNT_MISMATCH (investigate before ANY migration)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
