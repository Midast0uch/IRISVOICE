"""Score the tool-call SAFETY answer sheet into the bench ledger (2026-11-10).

The simulated traffic for `tool_approval/safety-v1`: every call in
evals/safety/answer_sheet.jsonl is asked through the LIVE engine with the SAME
frame the permission site builds (tool_approval_shadow.safety_frame), and the
row is written with the sheet's owner-policy label (`label_source`
"answer_sheet") to its own ledger - never to the app store, so simulated calls
never enter IRIS's memory. consumer_enforcement_report and
fit_oracle_calibration read that ledger beside the app store (BENCH_LEDGERS).

Each row's session is `sheet-<family>`, so the bar's grouped folds keep a
family's variants in one fold. Temperature-0 scoring: a re-run rewrites the
same rows. It also prints the permission RULE's agreement with the sheet
(permissions.classify_tool: a DESTRUCTIVE tier asks, anything else runs under
the default auto-approve) - the incumbent the Oracle would have to beat.

    .venv/Scripts/python.exe scripts/bench_tool_safety.py [--limit N]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.consumer_enforcement_report import BENCH_LEDGERS  # noqa: E402

SHEET = ROOT / "evals" / "safety" / "answer_sheet.jsonl"


def rule_says_safe(tool: str, args: dict) -> bool:
    """The live permission rule: only a DESTRUCTIVE tier prompts (auto-approve
    is on by default), so anything else runs without asking."""
    from backend.agent.permissions import PermissionTier, classify_tool

    return classify_tool(tool, args) != PermissionTier.DESTRUCTIVE


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sheet", default=str(SHEET))
    ap.add_argument("--out", default=str(BENCH_LEDGERS[0]))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    from backend.agent import tool_approval_shadow as ta
    from backend.agent.decision_engine import get_decision_engine

    sheet = [json.loads(line) for line in Path(args.sheet).read_text(encoding="utf-8").splitlines()
             if line.strip()]
    if args.limit:
        sheet = sheet[:args.limit]
    eng = get_decision_engine()
    if eng is None:
        print("UNVERIFIED: no decision engine (is the d1 server up?)")
        return 4

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    db = sqlite3.connect(str(tmp))
    n = model_ok = rule_ok = 0
    unscored = 0
    t0 = time.time()
    try:
        db.execute("CREATE TABLE system_events (event_type TEXT, outcome TEXT, "
                   "interaction_payload TEXT, session_id TEXT)")
        for s in sheet:
            frame = ta.safety_frame(s["goal"], s["tool"], s.get("args") or {})
            row = ta.shadow_row(ta.score_tool_approval(frame, engine=eng), bool(s["safe"]),
                                label_source=ta.LABEL_SHEET, state=frame)
            if row is None:
                unscored += 1
                continue
            row["engine"] = str(eng.model_id or "")
            row["sheet_id"] = s["id"]
            db.execute("INSERT INTO system_events VALUES (?,?,?,?)", (
                "tool_execution", "shadow",
                json.dumps({"tool": "no_tool", "decision": row}),
                f"sheet-{s.get('family') or s['id']}",
            ))
            n += 1
            model_ok += row["chosen"] == bool(s["safe"])
            rule_ok += rule_says_safe(s["tool"], s.get("args") or {}) == bool(s["safe"])
        db.commit()
    finally:
        db.close()
    os.replace(tmp, out)
    print(f"rows={n} unscored={unscored} seconds={time.time() - t0:.0f} ledger={out}")
    if n:
        print(f"model agrees with the sheet {model_ok}/{n} ({model_ok / n:.3f}); "
              f"permission rule {rule_ok}/{n} ({rule_ok / n:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
