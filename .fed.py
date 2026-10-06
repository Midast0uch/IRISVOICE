"""Throwaway: per-consumer row counts, against the full declared list."""
from __future__ import annotations

import json
import sqlite3

from backend.agent.decision_engine import CONSUMERS

c = sqlite3.connect("file:data/memory.db?mode=ro", uri=True)
c.row_factory = sqlite3.Row
counts: dict = {}
for r in c.execute(
    "SELECT interaction_payload FROM system_events "
    "WHERE event_type='tool_execution'"
):
    try:
        d = (json.loads(r["interaction_payload"] or "{}") or {}).get("decision")
    except Exception:
        continue
    if not isinstance(d, dict) or not d.get("consumer_id"):
        continue
    cid = str(d["consumer_id"])
    s = counts.setdefault(cid, {"n": 0, "ref": 0})
    s["n"] += 1
    if d.get("brain_choice") is not None or d.get("brain_bool") is not None:
        s["ref"] += 1

print(f"{'consumer':22} {'rows':>6} {'with_ref':>9}  status")
for cid in CONSUMERS:
    s = counts.get(cid, {"n": 0, "ref": 0})
    tag = "FED" if s["n"] else "NO ROWS YET"
    print(f"{cid:22} {s['n']:>6} {s['ref']:>9}  {tag}")
extra = {k: v for k, v in counts.items() if k not in CONSUMERS}
if extra:
    print("\nnot in the declared list:")
    for k, v in sorted(extra.items()):
        print(f"  {k:20} rows={v['n']}")
print("\ndeclared consumers with rows:",
      sum(1 for cid in CONSUMERS if counts.get(cid, {}).get("n")), "/", len(CONSUMERS))
c.close()
