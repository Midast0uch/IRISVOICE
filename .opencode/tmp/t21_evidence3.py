"""Session-318 T21 evidence pull, part 3: seeds, crash cause, commands, grade."""
import re

LOG = ".iris-logs/backend-20260910-095723.log"
lines = open(LOG, encoding="utf-8", errors="replace").read().splitlines()

def interesting(ln):
    if ln.startswith("2026-09-10 10:3") is False and "conv-103" not in ln and "run_command" not in ln and "CRASH" not in ln and "run grade" not in ln and "CrawlOrchestrator" not in ln and "Traceback" not in ln and "Error" not in ln and "error" not in ln.lower():
        return False
    if "httpcore" in ln or "httpx" in ln or "ws_manager" in ln or "structured_logger" in ln:
        return False
    return True

print("=== SEEDS / QUEUE / EXCLUSION / RECOVERY / GRADE (10:31+) ===")
for ln in lines:
    if "10:31" in ln[:22] or "10:32" in ln[:22] or "10:33" in ln[:22] or "10:34" in ln[:22] or "10:35" in ln[:22] or "10:36" in ln[:22] or "10:37" in ln[:22] or "10:38" in ln[:22]:
        if "CrawlOrchestrator" in ln and ("dispatch queue" in ln or "exclusion filtered" in ln or "recovery seeds" in ln or "plan.urls" in ln or "CRAWLER_STARTED" in ln or "zero_yield" in ln or "honest" in ln.lower() or "park_summary" in ln or "futile" in ln):
            print(ln[:300])

print("\n=== SEARCH CRASH + tracebacks ===")
for i, ln in enumerate(lines):
    if "CRASH" in ln or "Traceback" in ln:
        for j in range(i, min(i + 12, len(lines))):
            print(lines[j][:300])
        print("---")

print("\n=== run_command full commands ===")
seen = set()
for ln in lines:
    if "run_command" in ln and ("command" in ln or "Requested" in ln or "resolved" in ln):
        key = ln[:200]
        if key not in seen:
            seen.add(key)
            print(ln[:400])

print("\n=== run grade lines (all) ===")
for ln in lines:
    if "run grade" in ln:
        print(ln[:300])
print("(none above = grade never logged)")
