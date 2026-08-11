"""T6-PRE safety check: report memory_chain row counts in the real store."""
import os
import sqlite3

p = os.path.join(os.path.dirname(__file__), "..", "data", "memory.db")
p = os.path.abspath(p)
print("store:", p, "exists:", os.path.exists(p))
con = sqlite3.connect(p)
cur = con.cursor()
cur.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'memory_chain%'"
)
tables = [r[0] for r in cur.fetchall()]
print("memory_chain tables:", tables)
for t in tables:
    try:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        print(f"  {t}: {cur.fetchone()[0]} rows")
    except Exception as e:
        print(f"  {t}: ERROR {e}")
# Also confirm coordinate columns exist (T6 ALTER evidence)
try:
    cur.execute("PRAGMA table_info(memory_chain)")
    cols = [r[1] for r in cur.fetchall()]
    print("memory_chain columns:", cols)
except Exception as e:
    print("pragma error:", e)
con.close()
