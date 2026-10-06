"""Throwaway: what is the stray 'probe' consumer id, and which CANONICAL
consumers have produced no rows at all?

The canonical 15 live in backend/agent/decision_engine.py:64-95. Anything else
appearing as a consumer_id is NOT a Wave 7 consumer and must not be counted
against the bar.
"""
from __future__ import annotations

import json
import sqlite3

CANONICAL = (
    "tool_choice", "presentation", "narration", "recovery_strategy",
    "review_verdict", "sufficient", "done", "on_track", "mode", "web_intent",
    "retry_same", "has_gaps", "use_thinking", "escalate_incomplete",
    "needs_action",
)

c = sqlite3.connect("file:data/memory.db?mode=ro", uri=True)
counts: dict = {}
strays: list = []
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
    counts[cid] = counts.get(cid, 0) + 1
    if cid not in CANONICAL and len(strays) < 3:
        strays.append(d)
c.close()

print("canonical consumers with ZERO rows:")
for cid in CANONICAL:
    if cid not in counts:
        print("   ", cid)
print("\nstray consumer ids (not in the canonical 15):")
for cid in counts:
    if cid not in CANONICAL:
        print("   ", cid, "->", counts[cid], "row(s)")
print("\nsample stray payload:")
for s in strays[:2]:
    print("   ", json.dumps(s)[:300])
