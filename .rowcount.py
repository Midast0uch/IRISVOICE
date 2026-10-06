"""Throwaway: per-consumer row counts and scorable counts, as traffic runs."""
from __future__ import annotations

import json
import sqlite3

from backend.agent.decision_engine import CONSUMERS

DB = "data/memory.db"
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

# WHY THE FILTER (2026-09-27): this script used to print every id found under
# `decision.consumer_id`, so ONE self-test row written by an engine named
# "probe" appeared as a consumer with "99 to go" and was reported as an unfed
# Wave 7 consumer. It is not one. The bar is defined over the 15 consumers in
# backend/agent/decision_engine.py:64-95 and nothing else counts. The list is
# IMPORTED, not copied, so it cannot drift from the engine's own definition.
counts: dict = {}
strays: dict = {}
for (payload,) in c.execute(
    "SELECT interaction_payload FROM system_events "
    "WHERE event_type='tool_execution'"
):
    try:
        d = (json.loads(payload or "{}") or {}).get("decision")
    except Exception:
        continue
    if not isinstance(d, dict) or not d.get("consumer_id"):
        continue
    cid = str(d["consumer_id"])
    if cid in CONSUMERS:
        counts[cid] = counts.get(cid, 0) + 1
    else:
        strays[cid] = strays.get(cid, 0) + 1
c.close()

print(f"{'consumer':22} {'rows':>6} {'bar(100)':>10}")
met = 0
for cid in CONSUMERS:
    n = counts.get(cid, 0)
    if n >= 100:
        met += 1
    print(f"{cid:22} {n:>6} "
          f"{'MET' if n >= 100 else str(100 - n) + ' to go':>10}")
print(f"\n{met}/{len(CONSUMERS)} consumers MET"
      f"   total canonical rows: {sum(counts.values())}")

if strays:
    print("\nNOT consumers (excluded above) - a stray id is never a bar target:")
    for cid, n in sorted(strays.items(), key=lambda kv: -kv[1]):
        print(f"   {cid!r}: {n} row(s)")
