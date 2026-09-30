"""Harvest query (read-only) — count today's decision rows and the
final_choice join presence."""
import json
import sqlite3

from _app_store import app_store_path  # the configured store, not a stale copy

con = sqlite3.connect(f"file:{app_store_path()}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
rows = []
for r in con.execute(
    "SELECT interaction_payload, created_at FROM system_events "
    "WHERE event_type='tool_execution' AND created_at >= '2026-09-20'"
):
    try:
        d = json.loads(r[0] or "{}").get("decision")
    except Exception:
        continue
    if isinstance(d, dict):
        rows.append(d | {"_ts": r["created_at"]})

print("total engine rows today:", len(rows))
tc = [r for r in rows if r.get("consumer_id") == "tool_choice"]
print("tool_choice rows:", len(tc))
joined = [r for r in tc if "final_choice" in r]
print("with final_choice join:", len(joined))
for r in joined[:12]:
    print(" ", r.get("chosen"), "->", r.get("final_choice"),
          "| correct:", r.get("engine_correct"), "| conf:", r.get("confidence"))
print("\n5 most recent rows full payload inspection:")
for r in sorted(rows, key=lambda x: str(x.get("_ts")), reverse=True)[:5]:
    print(json.dumps(r, default=str)[:300])
