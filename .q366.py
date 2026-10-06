"""Session-366: per-consumer counts incl. depth_route, from data/memory.db."""
import sqlite3

DB = "data/memory.db"
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
print("max rowid:", c.execute("SELECT MAX(rowid) FROM system_events").fetchone())

SQL = (
    "SELECT json_extract(interaction_payload, '$.decision.consumer_id') cid, "
    "COUNT(*) n FROM system_events WHERE event_type='tool_execution' "
    "GROUP BY cid HAVING cid IS NOT NULL ORDER BY n DESC"
)
print("--- consumer counts ---")
for cid, n in c.execute(SQL):
    print(f"  {cid:24} {n}")

print("--- depth_route rows ---")
rows = c.execute(
    "SELECT rowid, created_at, "
    "json_extract(interaction_payload, '$.decision.chosen'), "
    "json_extract(interaction_payload, '$.decision.brain_choice'), "
    "json_extract(interaction_payload, '$.decision.confidence') "
    "FROM system_events "
    "WHERE json_extract(interaction_payload, '$.decision.consumer_id')='depth_route'"
).fetchall()
print("count:", len(rows))
for r in rows:
    print("  ", r)

print("--- done rows ---")
rows = c.execute(
    "SELECT rowid, created_at, "
    "json_extract(interaction_payload, '$.decision.chosen'), "
    "json_extract(interaction_payload, '$.decision.brain_bool') "
    "FROM system_events "
    "WHERE json_extract(interaction_payload, '$.decision.consumer_id')='done'"
).fetchall()
print("count:", len(rows))
for r in rows:
    print("  ", r)
c.close()
