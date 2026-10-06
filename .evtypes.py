"""Throwaway: is the row counter missing rows because of the event_type filter?

.rowcount.py counts only event_type='tool_execution'. If the loop-monitor
consumers (sufficient / done / on_track) are recorded under another event type,
they would read as "0 rows" while actually being written. Check before
concluding that a consumer is unwired.
"""
from __future__ import annotations

import json
import sqlite3

c = sqlite3.connect("file:data/memory.db?mode=ro", uri=True)

print("event_types in system_events:")
for t, n in c.execute(
    "SELECT event_type, COUNT(*) FROM system_events "
    "GROUP BY event_type ORDER BY 2 DESC"
):
    print(f"   {t!r}: {n}")

seen: dict = {}
for t, payload in c.execute(
    "SELECT event_type, interaction_payload FROM system_events"
):
    try:
        d = (json.loads(payload or "{}") or {}).get("decision")
    except Exception:
        continue
    if isinstance(d, dict) and d.get("consumer_id"):
        k = (str(t), str(d["consumer_id"]))
        seen[k] = seen.get(k, 0) + 1

print("\ndecision.consumer_id, by event_type (ANY type, not just tool_execution):")
for (t, cid), n in sorted(seen.items(), key=lambda kv: -kv[1]):
    print(f"   {cid:22} under {t:20} {n}")
c.close()
