"""Measure the tool_choice action-class label on the stored v7 rows.

Usage:  python scripts/action_class_label.py
Read-only. Prints accuracy, the confusion matrix, the misses, and how many
side-effect picks were recorded (sampled mode drops them before the row).
"""
import json
import os
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _app_store import app_store_path  # noqa: E402
from backend.memory.db import open_store_read_only  # noqa: E402
from backend.agent.tool_choice_action_class import (  # noqa: E402
    UNKNOWN, action_class_ok, classify_tool, required_classes,
)


def goal_and_calls(state):
    text = str(state or "")
    goal = re.split(r"\n|done_when:", text, maxsplit=1)[0].strip()
    m = re.search(r"calls_this_step:\s*(.*?)(?:\n|$)", text)
    return goal, (m.group(1) if m else "")


def main() -> int:
    c = open_store_read_only(app_store_path())
    q = ("SELECT interaction_payload FROM system_events "
         "WHERE event_type='tool_execution' ORDER BY rowid DESC LIMIT 12000")
    rows = []
    for (p,) in c.execute(q):
        try:
            d = json.loads(p)
        except Exception:
            continue
        r = d.get("decision")
        if not isinstance(r, dict):
            continue
        if r.get("consumer_id") != "tool_choice" \
                or r.get("criteria_version") != "tc-decide-v7":
            continue
        rows.append(r)

    classes = {}
    for r in rows:
        k = classify_tool(r.get("chosen"))
        classes[k] = classes.get(k, 0) + 1
    print("v7 rows:", len(rows), "| chosen classes:", classes)

    scored = correct = 0
    confusion = {}
    misses = []
    for r in rows:
        goal, calls = goal_and_calls(r.get("state"))
        step_id = str(r.get("step_id") or "")
        need = required_classes(goal, calls, step_id)
        if need is None:
            continue
        got = classify_tool(r.get("chosen"))
        if got == UNKNOWN:
            continue
        scored += 1
        ok = action_class_ok(r.get("chosen"), goal, calls, step_id)
        correct += 1 if ok else 0
        key = (",".join(sorted(need)), got)
        confusion[key] = confusion.get(key, 0) + 1
        if not ok:
            misses.append((sorted(need), got, r.get("chosen"),
                           r.get("confidence"), goal[:90], step_id))

    print("scored:", scored, "correct:", correct,
          "accuracy:", round(correct / scored, 4) if scored else None)
    print("confusion (required, got):", confusion)
    print("\nmisses:")
    for m in misses[:20]:
        print("  req=%s got=%s tool=%s conf=%s step=%s goal=%s" % m)
    side = sum(1 for r in rows
               if classify_tool(r.get("chosen")) in ("WRITE", "RUN"))
    print("\nside-effect picks recorded (WRITE/RUN):", side)
    print("NOTE: sampled mode drops side-effect picks before the row is built "
          "(IRIS_ORACLE_SAMPLE_SIDE_EFFECTS off), so the measured set is "
          "read-only by construction.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
