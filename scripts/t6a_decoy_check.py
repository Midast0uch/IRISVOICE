"""T6a(d): inspect the decoy backend/data/memory.db — is it dead or written?"""
import os
import sqlite3

p = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend", "data", "memory.db"))
print("decoy:", p, "exists:", os.path.exists(p))
if os.path.exists(p):
    con = sqlite3.connect(p)
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print("tables:", len(tables))
    for t in ("memory_chain", "memory_chain_v2"):
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            print(f"  {t}: {cur.fetchone()[0]} rows")
        except Exception as e:
            print(f"  {t}: absent ({e})")
    try:
        cur.execute("PRAGMA table_info(memory_chain)")
        print("memory_chain cols:", [r[1] for r in cur.fetchall()])
    except Exception as e:
        print("pragma:", e)
    con.close()
