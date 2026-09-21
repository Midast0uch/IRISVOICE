"""Session-318 T21 evidence pull, part 2: seeds, crash, tail."""
import re

LOG = ".iris-logs/backend-20260910-095723.log"
lines = open(LOG, encoding="utf-8", errors="replace").read().splitlines()
print("total lines:", len(lines))

print("\n=== SEED QUEUE LINES (conv-103 window) ===")
for ln in lines:
    if "10:3" in ln[:22] and ("dispatch queue" in ln or "dispatch job_id" in ln and "urls=" in ln or "exclusion filtered" in ln or "recovery seeds" in ln or "plan.urls" in ln.lower() or "CRAWLER_STARTED" in ln):
        print(ln[:300])

print("\n=== CRASH CONTEXT (10:37:20-10:38:00) ===")
for ln in lines:
    if ln[:22] >= "2026-09-10 10:37:20" and ln[:22] <= "2026-09-10 10:38:05":
        print(ln[:320])

print("\n=== LOG TAIL (last 12) ===")
for ln in lines[-12:]:
    print(ln[:300])
