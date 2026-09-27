"""Unit tests: the per-consumer enforcement report (T22/T52, REQ-31).

The report is the instrument Wave 7 flips on, so its LABEL rules are the
contract: a precision number is meaningless without saying what "correct"
means, and a row with no reference answer must be counted as skipped rather
than quietly credited as correct.
"""

from __future__ import annotations

import json
import sqlite3

from scripts.consumer_enforcement_report import (
    bar_rows,
    build_report,
    load_rows,
)


def _db(tmp_path, rows):
    """A real (tiny) system_events table, so the loader is exercised."""
    p = tmp_path / "memory.db"
    c = sqlite3.connect(str(p))
    c.execute(
        "CREATE TABLE system_events (outcome TEXT, event_type TEXT, "
        "interaction_payload TEXT)"
    )
    for outcome, payload in rows:
        c.execute(
            "INSERT INTO system_events VALUES (?, 'tool_execution', ?)",
            (outcome, json.dumps(payload)),
        )
    c.commit()
    c.close()
    return str(p)


def _shadow(cid="sufficient", chosen=True, brain=True, conf=0.9, **extra):
    d = {"consumer_id": cid, "chosen": chosen, "confidence": conf,
         "route": "shadow", "shadow": True}
    if brain is not None:
        d["brain_bool"] = brain
    d.update(extra)
    return {"tool": "no_tool", "decision": d}


class TestTheLabelRules:
    def test_a_shadow_row_is_labelled_by_parity_with_the_brain(self, tmp_path):
        db = _db(tmp_path, [
            (None, _shadow(chosen=True, brain=True, conf=0.9)),
            (None, _shadow(chosen=False, brain=True, conf=0.9)),
        ])
        rows, skipped = load_rows(db)
        assert [r["correct"] for r in rows] == [True, False]
        assert skipped["no_label"] == 0

    def test_a_shadow_row_without_a_reference_is_skipped_not_credited(
        self, tmp_path,
    ):
        """The trap this rule exists for: reading a missing reference as a
        success inflates every precision number to 1.0."""
        db = _db(tmp_path, [(None, _shadow(brain=None))])
        rows, skipped = load_rows(db)
        assert rows == [], "an unlabelled row produced a measurement"
        assert skipped["no_label"] == 1

    def test_a_dispatched_row_is_labelled_by_the_event_outcome(self, tmp_path):
        db = _db(tmp_path, [
            ("success", {"tool": "read_file", "decision":
                         {"consumer_id": "tool_choice", "chosen": "read_file",
                          "confidence": 0.7}}),
            ("failure", {"tool": "read_file", "decision":
                         {"consumer_id": "tool_choice", "chosen": "read_file",
                          "confidence": 0.7}}),
        ])
        rows, _skipped = load_rows(db)
        assert [r["correct"] for r in rows] == [True, False]
        assert all(r["shadow"] is False for r in rows)


class TestTheMeasurement:
    def test_precision_is_measured_at_the_threshold(self):
        from scripts.consumer_enforcement_report import measure

        rows = [
            # Above 0.40 and correct.
            {"consumer_id": "c", "confidence": 0.9, "correct": True, "shadow": True,
             "engine": "e"},
            {"consumer_id": "c", "confidence": 0.6, "correct": True, "shadow": True,
             "engine": "e"},
            # ABOVE the threshold but WRONG — must sink the precision.
            {"consumer_id": "c", "confidence": 0.5, "correct": False, "shadow": True,
             "engine": "e"},
            # BELOW the threshold: evidence volume, not precision.
            {"consumer_id": "c", "confidence": 0.1, "correct": False, "shadow": True,
             "engine": "e"},
        ]
        m = measure(rows, {"c": 0.4})["c"]
        assert m["rows"] == 4, "the evidence volume must count every labelled row"
        assert m["rows_above_threshold"] == 3
        assert m["precision"] == round(2 / 3, 4)
        assert m["ece"] is not None, "ECE must be computed, not omitted"

    def test_the_bar_is_tg7s_and_the_gap_is_named(self):
        measured = {
            "ready": {"rows": 200, "precision": 0.95, "ece": 0.01,
                      "rows_above_threshold": 180, "brier": 0.02, "threshold": 0.4,
                      "shadow_rows": 200, "engines": ["e"]},
            "too_few": {"rows": 40, "precision": 0.99, "ece": 0.01,
                        "rows_above_threshold": 40, "brier": 0.02,
                        "threshold": 0.4, "shadow_rows": 40, "engines": ["e"]},
            "uncalibrated": {"rows": 200, "precision": 0.95, "ece": 0.30,
                             "rows_above_threshold": 200, "brier": 0.2,
                             "threshold": 0.4, "shadow_rows": 200,
                             "engines": ["e"]},
        }
        rep = build_report(measured, {}, {"backend_id": "b", "candidate_cap": 6})
        assert rep["flipped"] == ["ready"]
        assert "rows 40" in rep["consumers"]["too_few"]["gap"]
        assert "ECE" in rep["consumers"]["uncalibrated"]["gap"]

    def test_a_backend_with_no_threshold_cannot_flip(self):
        """AC25.8 fail-closed: numbers alone never enforce when the active
        backend has no threshold entry."""
        measured = {
            "c": {"rows": 500, "precision": 0.99, "ece": 0.01,
                  "rows_above_threshold": 500, "brier": 0.01, "threshold": None,
                  "shadow_rows": 500, "engines": ["unknown-backend"]},
        }
        rep = build_report(measured, {}, {"backend_id": "", "candidate_cap": 6})
        assert rep["flipped"] == []
        assert "fail-closed" in rep["consumers"]["c"]["gap"]
        # ...and the persisted artifact agrees, because no ECE is carried.
        assert bar_rows(measured)["c"]["ece"] is None
