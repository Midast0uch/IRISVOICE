"""tool_choice is certified as the CLASS ROLE, at the gate the app uses.

Found 2026-11-10: the bar ranked tool_choice by its confidence in the chosen
TOOL while the role decides the tool CLASS and acts on the class margin; and
the action-class label scored every pick of an unmapped tool (crawler_query,
browser_open, search, stop_command: 62 outcome rows, all "wrong") although the
role never class-decides such a tool. Scored on what it decides, at its live
gate (margin >= CLASS_MARGIN_MIN), tc-decide-v9 meets every clause.
Pinned: the margin is the confidence, an unmapped pick is unscoreable, the
policy point is the live gate, and the certified record can never gate the
forced path's tool confidence.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.agent.tool_choice_action_class import CLASS_MARGIN_MIN  # noqa: E402
from scripts import fit_oracle_calibration as fit  # noqa: E402
from scripts.consumer_enforcement_report import (  # noqa: E402
    class_margin_confidence,
    load_rows,
)


def _row(chosen, cands, ok=True):
    return {"consumer_id": "tool_choice", "engine": "d1-x", "chosen": chosen,
            "confidence": 0.99, "candidates": cands, "label_source": "action_class",
            "outside_label": ok, "criteria_version": "tc-decide-v9", "route": "class"}


def _ledger(tmp_path, decisions):
    db = tmp_path / "ledger.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE system_events (event_type TEXT, outcome TEXT, "
              "interaction_payload TEXT, session_id TEXT)")
    for d in decisions:
        c.execute("INSERT INTO system_events VALUES (?,?,?,?)",
                  ("tool_execution", "success", json.dumps({"decision": d}), "s1"))
    c.commit()
    c.close()
    return str(db)


def test_the_confidence_is_the_class_margin():
    cands = [{"name": "read_file", "prob": 0.6}, {"name": "grep_files", "prob": 0.2},
             {"name": "edit_file", "prob": 0.15}, {"name": "run_command", "prob": 0.05}]
    # READ mass 0.8 against the strongest rival class (WRITE 0.15)
    assert abs(class_margin_confidence(_row("read_file", cands)) - 0.65) < 1e-9


def test_an_unmapped_pick_is_unscoreable_not_wrong(tmp_path):
    good = _row("read_file", [{"name": "read_file", "prob": 0.9},
                              {"name": "edit_file", "prob": 0.1}])
    web = _row("crawler_query", [{"name": "crawler_query", "prob": 0.9},
                                 {"name": "read_file", "prob": 0.1}], ok=False)
    rows, skipped = load_rows(_ledger(tmp_path, [good, web]))
    assert [r["chosen"] for r in rows] == ["read_file"]
    assert skipped["unscoreable_unmapped"] == 1
    assert abs(rows[0]["confidence"] - 0.8) < 1e-9, "scored by the class margin"


def test_the_policy_point_is_the_live_class_gate():
    assert fit.POLICY_RAW_THRESHOLD["tool_choice"] == CLASS_MARGIN_MIN


def test_the_certified_record_never_gates_tool_confidence():
    src = (_ROOT / "backend" / "agent" / "tool_decision.py").read_text(
        encoding="utf-8", errors="replace")
    assert 'enforced = _class_mode and decides("tool_choice") is not None' in src
    assert "not _shortlist_k and not _class_mode" in src
