"""Every consumer row must carry a PARITY REFERENCE, or it cannot be scored.

WHY THIS FILE EXISTS (2026-09-27)

The ledger already held rows. They could not be scored, which is what blocked
"finish Oracle". Measured with a direct read of data/memory.db before the fix:

  consumer            rows  chosen  brain_bool  brain_choice  scorable
  tool_choice          459     459           0             0  dispatched
  presentation         123     123           0             0  NO
  escalate_incomplete    4       4           4             0  yes
  mode                   2       0           0             0  NO

Two ways a row is unscoreable, and both are pinned here:

  1. It carries NO reference at all (presentation had none). The report must
     count that as SKIPPED, never as correct - a row with no reference is not
     evidence of a right answer.
  2. It carries the reference under a KEY THE LEDGER DOES NOT PASS. mode used
     engine_mode/keyword_mode, the reviewer used brain_verdict, the triage used
     counter_choice. `_DECISION_META_KEYS` is the whitelist, so all three were
     dropped on the way to the ledger and the row arrived with no reference.

The two reference shapes are pinned too, because a LABEL consumer and a BOOL
consumer need different comparisons, and collapsing a name to a bool would
manufacture agreement and inflate precision:

  brain_bool   - bool vs bool   (sufficient, done, has_gaps, ...)
  brain_choice - name vs name   (mode, review_verdict, presentation, web_intent)
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from backend.agent.explorer import (  # noqa: E402
    WEB_INTENT_CONSUMER,
    _engine_web_intent,
    set_row_sink,
)
from backend.agent.tool_bridge import _DECISION_META_KEYS  # noqa: E402
from scripts.consumer_enforcement_report import load_rows  # noqa: E402


def _ledger(tmp_path, decisions):
    """A minimal system_events ledger holding the given decision blocks."""
    db = tmp_path / "ledger.db"
    c = sqlite3.connect(str(db))
    c.execute(
        "CREATE TABLE system_events ("
        "event_type TEXT, outcome TEXT, interaction_payload TEXT)"
    )
    for d in decisions:
        c.execute(
            "INSERT INTO system_events VALUES (?,?,?)",
            ("tool_execution", "success", json.dumps({"decision": d})),
        )
    c.commit()
    c.close()
    return str(db)


# -- The whitelist must pass the reference through --------------------------

def test_the_label_reference_is_on_the_ledger_whitelist():
    """`brain_choice` must survive tool_bridge's meta filter. If it does not,
    every label consumer's reference is dropped on the way to the ledger and the
    row lands unscoreable while looking complete."""
    assert "brain_choice" in _DECISION_META_KEYS
    assert "brain_bool" in _DECISION_META_KEYS
    assert "chosen" in _DECISION_META_KEYS


# -- The report's two label shapes -----------------------------------------

def test_a_label_reference_scores_a_shadow_row(tmp_path):
    """chosen vs brain_choice, name against name."""
    db = _ledger(tmp_path, [{
        "consumer_id": "mode", "chosen": "spec", "brain_choice": "spec",
        "confidence": 0.9, "shadow": True,
    }])
    rows, skipped = load_rows(db)
    assert len(rows) == 1 and not skipped["no_label"]
    assert rows[0]["correct"] is True


def test_a_label_reference_that_DISAGREES_is_incorrect(tmp_path):
    """The metric must be able to go DOWN, or it measures nothing."""
    db = _ledger(tmp_path, [{
        "consumer_id": "mode", "chosen": "quick", "brain_choice": "spec",
        "confidence": 0.9, "shadow": True,
    }])
    rows, _skipped = load_rows(db)
    assert rows[0]["correct"] is False


def test_a_bool_reference_still_scores_as_a_bool(tmp_path):
    """The pre-existing shape must keep working unchanged."""
    db = _ledger(tmp_path, [{
        "consumer_id": "escalate_incomplete", "chosen": True, "brain_bool": True,
        "confidence": 0.9, "shadow": True,
    }])
    rows, _skipped = load_rows(db)
    assert rows[0]["correct"] is True


def test_a_row_with_no_reference_is_SKIPPED_not_scored(tmp_path):
    """No reference -> no label. Counting it as correct would inflate precision."""
    db = _ledger(tmp_path, [{
        "consumer_id": "presentation", "chosen": "prism_card",
        "confidence": 0.9, "shadow": True,
    }])
    rows, skipped = load_rows(db)
    assert rows == []
    assert skipped["no_label"] == 1


def test_a_different_vocabulary_would_read_as_disagreement(tmp_path):
    """Why the presentation row TRANSLATES the live surface into the engine's
    vocabulary: "plain" and "plain_text" are the same surface under two names,
    and comparing the raw strings would report a false disagreement."""
    db = _ledger(tmp_path, [{
        "consumer_id": "presentation", "chosen": "plain_text",
        "brain_choice": "plain",  # raw, untranslated
        "confidence": 0.9, "shadow": True,
    }])
    rows, _skipped = load_rows(db)
    assert rows[0]["correct"] is False, (
        "documents the trap, not a desired behaviour: it is why "
        "_engine_gate_surface maps plain->plain_text before recording"
    )


# -- The web_intent consumer's row path ------------------------------------

class _FakeNoul:
    def __init__(self, prob):
        self.probability = prob
        self.engine_latency_ms = 12.0

    def true(self, threshold):
        return self.probability >= threshold


class _FakeEngine:
    model_id = "fake-engine"

    def __init__(self, prob):
        self._prob = prob

    def noul(self, consumer_id, statement, frame, true_label, false_label):
        assert consumer_id == WEB_INTENT_CONSUMER
        return _FakeNoul(self._prob)


def test_web_intent_emits_a_row_with_both_halves():
    """The consumer had no row path at all: it scored and wrote nothing."""
    seen = []
    set_row_sink(seen.append)
    try:
        verdict = _engine_web_intent(
            "search the web for the price", _FakeEngine(0.93), keyword=True
        )
    finally:
        set_row_sink(None)
    assert verdict is True
    assert len(seen) == 1, "the engine scored but nothing was emitted"
    row = seen[0]
    assert row["consumer_id"] == WEB_INTENT_CONSUMER
    assert row["chosen"] == "yes"
    assert row["brain_choice"] == "yes", "the keyword answer is the reference"
    assert row["shadow"] is True
    assert row["confidence"] == 0.93


def test_web_intent_records_a_disagreement_honestly():
    """Engine says yes, the keyword heuristic says no: the row must show it."""
    seen = []
    set_row_sink(seen.append)
    try:
        _engine_web_intent("tell me a joke", _FakeEngine(0.91), keyword=False)
    finally:
        set_row_sink(None)
    assert seen[0]["chosen"] == "yes"
    assert seen[0]["brain_choice"] == "no"


def test_web_intent_without_a_sink_does_not_raise():
    """No sink installed -> the row is logged, never silently dropped, and the
    caller still gets its verdict."""
    set_row_sink(None)
    assert (
        _engine_web_intent("search the web", _FakeEngine(0.9), keyword=True)
        is True
    )


def test_web_intent_without_an_engine_emits_nothing():
    """No engine -> no row. A missing scorer must never fabricate one."""
    seen = []
    set_row_sink(seen.append)
    try:
        assert _engine_web_intent("search the web", None, keyword=True) is None
    finally:
        set_row_sink(None)
    assert seen == []
