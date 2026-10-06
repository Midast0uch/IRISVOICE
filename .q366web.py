"""Session-366: web_intent confusion matrix (engine vs the keyword reference)."""
import json
import sqlite3

DB = "data/memory.db"
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
SQL = (
    "SELECT interaction_payload FROM system_events "
    "WHERE event_type='tool_execution'"
)
rows = []
for (payload,) in c.execute(SQL):
    try:
        d = (json.loads(payload or "{}") or {}).get("decision")
    except Exception:
        continue
    if not isinstance(d, dict) or d.get("consumer_id") != "web_intent":
        continue
    rows.append(d)
c.close()

print("web_intent rows:", len(rows))
# engine chosen is a label name; the reference is the keyword bool.
agree = dis = 0
eng_yes = 0
over_yes = []   # engine YES while keyword said NO
for d in rows:
    ch = str(d.get("chosen", "")).lower()
    ref = d.get("brain_choice")
    if isinstance(ref, bool):
        ref = "yes" if ref else "no"
    ref = str(ref).lower()
    if ch == "yes":
        eng_yes += 1
    if ref in ("yes", "no"):
        if ch == ref:
            agree += 1
        else:
            dis += 1
            if ch == "yes":
                over_yes.append((d.get("confidence"), d.get("goal") or d.get("goal_text") or ""))
print(f"engine YES: {eng_yes} / {len(rows)}")
print(f"agree with keyword: {agree}   disagree: {dis}")
print(f"engine YES while keyword NO (the over-trigger): {len(over_yes)}")
for conf, goal in over_yes[:12]:
    print(f"   conf={conf}  goal={str(goal)[:90]!r}")
