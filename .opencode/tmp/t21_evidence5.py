"""Session-318 T21 evidence pull, part 5: 404 layers + docstore s1 result."""
import re

LOG = ".iris-logs/backend-20260910-095723.log"
lines = open(LOG, encoding="utf-8", errors="replace").read().splitlines()

print("=== 404 lines (no httpx noise) ===")
for ln in lines:
    if "404" in ln and "httpcore" not in ln and "httpx" not in ln:
        print(ln[:320])

print("\n=== parked/walled/run_budget/dead outcomes (10:31-10:38) ===")
for ln in lines:
    if ("10:3" in ln[:22]) and ("park" in ln.lower() or "walled" in ln.lower() or "run_budget" in ln or "dead" in ln.lower() or "usable" in ln.lower()):
        if "httpcore" not in ln and "httpx" not in ln:
            print(ln[:300])
