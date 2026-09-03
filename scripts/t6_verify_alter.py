"""T6 verify: does the engine's fallback migration apply the coordinate ALTER
to the REAL store when run against it (production fallback path)?"""
import os
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.chdir(Path(__file__).resolve().parent.parent)

REAL = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "memory.db"))
WORK = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "memory_t6_test.db"))

# Never touch the real store — copy to a work file first (T6-PRE backup also exists).
shutil.copy2(REAL, WORK)
print("work copy:", WORK)

from backend.gateway.iris_ffi import _PythonFallbackEngine

eng = _PythonFallbackEngine(db_path=WORK, key_hex="00" * 32)
con = sqlite3.connect(WORK)
cols = {r[1] for r in con.execute("PRAGMA table_info(memory_chain)")}
rows = con.execute("SELECT COUNT(*) FROM memory_chain").fetchone()[0]
tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
con.close()
print("has coords_from:", "coords_from" in cols)
print("has mediator:", "mediator" in cols)
print("memory_chain rows:", rows)
print("memory_chain_v2 present:", "memory_chain_v2" in tables)

ok = ("coords_from" in cols) and ("mediator" in cols) and ("memory_chain_v2" not in tables)
print("T6_ALTER_APPLIED" if ok else "T6_ALTER_NOT_APPLIED")
# cleanup work copy
os.remove(WORK)
