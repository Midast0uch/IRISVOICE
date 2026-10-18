"""Contract: the EXTERNAL turn-verdict label (depth_met/v3, oracle.md 7.5).

Why it exists (measured live 2026-10-17): depth_met's incumbent reference is
the loop grade - a deterministic rule over inputs the model never sees - so
the Oracle cannot beat it (oof AUROC 0.40, confidence ranked errors
BACKWARDS). The honest label is whether the TURN was actually right: the eval
verdict (hidden tests) for eval turns, a user correction for live turns. That
verdict exists only outside the process, so the row is HELD until
POST /api/eval/verdict reports it.

These tests pin the safety properties:
  - a row with no turn_id is NOT held (no join key -> parity only);
  - nothing here can block a consult or a turn (never raises);
  - parity and outcome stay SEPARATE (label_source says which curve);
  - the pending map is bounded and the drop is counted.
"""
from __future__ import annotations

import pytest

from backend.agent import turn_verdict_label as tvl


@pytest.fixture(autouse=True)
def _clean():
    tvl.reset()
    yield
    tvl.reset()


def _row(turn="t1", chosen=True):
    return {
        "consumer_id": "depth_met",
        "chosen": chosen,
        "brain_bool": True,
        "confidence": 0.8,
        "shadow": True,
        "criteria_version": "depth_met/v3",
        "turn_id": turn,
    }


# ── the label itself ───────────────────────────────────────────────────────

def test_a_passing_verdict_makes_met_right():
    written = []
    assert tvl.defer(_row(chosen=True), written.append) is True
    assert written == [], "held, not written"
    assert tvl.report_verdict("t1", passed=True) == 1
    assert written[0]["outside_label"] is True
    assert written[0]["label_source"] == "outcome"


def test_a_failing_verdict_makes_met_wrong():
    """The case the loop grade CANNOT see: the loop said pass, the hidden
    tests said the turn was wrong."""
    written = []
    tvl.defer(_row(chosen=True), written.append)
    tvl.report_verdict("t1", passed=False)
    assert written[0]["outside_label"] is False
    assert written[0]["label_source"] == "outcome"


def test_the_parity_pair_survives_the_label():
    written = []
    tvl.defer(_row(chosen=True), written.append)
    tvl.report_verdict("t1", passed=False)
    assert written[0]["brain_bool"] is True   # the loop's own grade, intact
    assert written[0]["chosen"] is True       # the engine's answer, intact


def test_a_verdict_for_an_unknown_turn_is_a_no_op():
    tvl.defer(_row(), lambda r: None)
    assert tvl.report_verdict("never-held", passed=True) == 0
    assert tvl.stats()["rows_pending"] == 1  # the held row is untouched


# ── the join and the emission ──────────────────────────────────────────────

def test_a_row_without_a_turn_id_is_not_held():
    written = []
    assert tvl.defer(_row(turn=""), written.append) is False
    assert written == [], "the caller writes it exactly as before"
    assert tvl.stats()["rows_pending"] == 0


def test_every_held_row_is_written_exactly_once():
    written = []
    tvl.defer(_row(), written.append)
    tvl.defer(_row(), written.append)
    assert tvl.report_verdict("t1", passed=True) == 2
    assert len(written) == 2
    assert tvl.report_verdict("t1", passed=True) == 0
    assert len(written) == 2


def test_a_verdict_only_touches_its_own_turn():
    tvl.defer(_row(turn="t1"), lambda r: None)
    tvl.defer(_row(turn="t2"), lambda r: None)
    tvl.report_verdict("t1", passed=True)
    st = tvl.stats()
    assert st["turns_pending"] == 1 and st["rows_pending"] == 1


# ── the sweep: no verdict, no loss ─────────────────────────────────────────

def test_sweep_flushes_unlabelled_rows_on_parity():
    """A live turn or a crashed harness never reports: the row is still a
    real measurement on its parity reference. Dropping it would lose
    evidence; guessing a label would be phantom adjudication."""
    written = []
    tvl.defer(_row(), written.append)
    assert tvl.sweep() == 1
    assert len(written) == 1
    assert "outside_label" not in written[0]
    assert "label_source" not in written[0]


# ── bounded, and the drop is counted ───────────────────────────────────────

def test_the_pending_map_is_bounded_and_counts_its_drops():
    for i in range(tvl._CAP + 7):
        tvl.defer(_row(turn=f"t{i}"), lambda r: None)
    st = tvl.stats()
    assert st["turns_pending"] <= tvl._CAP
    assert st["dropped_overflow"] >= 7


# ── never raises ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [None, 0, "", [], {}, object()])
def test_defer_never_raises(bad):
    assert tvl.defer(bad, lambda r: None) is False


@pytest.mark.parametrize("bad", [None, 0, "", [], {}])
def test_report_never_raises(bad):
    tvl.report_verdict(bad, bad)


def test_a_writer_failure_never_propagates():
    def _boom(_row):
        raise RuntimeError("writer down")

    tvl.defer(_row(), _boom)
    assert tvl.report_verdict("t1", passed=True) == 1
