"""Contract: the tool_choice row is labelled by the STEP'S COMPLETION.

tc-decide-v7 (2026-11-07). The decided row asks "which tool next"; the outside
reference that answers it is whether the step that used the pick COMPLETED.
`outside_label` is True only when BOTH hold:

    * the CALL succeeded (the row's own `outcome_label == "ok"`), and
    * the step was NOT retried (it reached finalize with no failure and no
      post-finalize artifact graft).

Two earlier labels are why this rule exists, and both are pinned here as
history, not as behaviour:
    * v4 (call-age): on a binding pick `called == chosen` is true by
      construction, so the label reduced to `ok` - "the call ran", not "the
      right TOOL was chosen" (698 rows, oof AUROC 0.5849);
    * v6 (verified_label): the DER verifier grades the step's OUTPUT text
      against expected text, so a successful read is UNVERIFIED. The live gate
      produced 19 settled rows, ALL UNVERIFIED - a single-class label that
      cannot rank anything.

These pin the mechanics, not the code:
  * the flag is the off switch (off = no hold, the call-age label stands);
  * ok+completed -> True; ok+retried -> False; failed+anything -> False;
  * the key is (turn, step): the step id is an ORDINAL, so two turns collide
    without the turn;
  * a step may hold MANY rows (one per tool call) and every one is stamped;
  * an unsettled step is SWEPT with no outside_label (counted, never scored);
  * a parity/shadow row and a "finished"/"overridden" row pass straight through;
  * a row that arrives after its step settled is labelled immediately;
  * the hold is bounded.
"""
from __future__ import annotations

import pytest

from backend.agent import tool_choice_outcome_label as tcol

FLAG = "IRIS_ORACLE_TOOL_CHOICE_OUTCOME"


def _row(step="s1", turn="t1", outcome="ok"):
    return {
        "consumer_id": "tool_choice",
        "label_source": "outcome",
        "outcome_label": outcome,
        "chosen": "read_file",
        "step_id": step,
        "turn_id": turn,
    }


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    tcol.reset()
    monkeypatch.setenv(FLAG, "1")
    yield
    tcol.reset()


def test_flag_off_never_holds(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    wrote: list = []
    assert tcol.defer(_row(), lambda r: wrote.append(r)) is False
    assert wrote == []
    assert tcol.stats()["pending_rows"] == 0


def test_the_label_is_the_truth_table_of_call_and_step():
    # (call outcome, step completed) -> explained pick?
    cases = [
        ("ok", True, True, "COMPLETED"),     # call worked, step completed
        ("ok", False, False, "FAILED"),      # call worked, step retried
        ("failed", True, False, "COMPLETED"),  # call failed, step completed
        ("failed", False, False, "FAILED"),  # both failed
    ]
    for i, (call, step_ok, want, step_outcome) in enumerate(cases):
        step = f"v{i}"
        wrote: list = []
        assert tcol.defer(_row(step, outcome=call), lambda r, out=wrote: out.append(dict(r)))
        assert wrote == []  # held, not written at call time
        assert tcol.stamp(step, "t1", step_ok) == 1
        assert wrote[0]["outside_label"] is want
        assert wrote[0]["label_reference"] == "step_completed"
        assert wrote[0]["step_outcome"] == step_outcome


def test_the_key_is_turn_plus_step():
    a: list = []
    b: list = []
    tcol.defer(_row("s2", "tA"), lambda r: a.append(dict(r)))
    tcol.defer(_row("s2", "tB"), lambda r: b.append(dict(r)))
    assert tcol.stamp("s2", "tA", True) == 1
    assert a[0]["outside_label"] is True and b == []
    assert tcol.stamp("s2", "tB", False) == 1
    assert b[0]["outside_label"] is False


def test_every_row_of_a_step_is_stamped_once():
    wrote: list = []
    for _ in range(3):
        tcol.defer(_row("s3"), lambda r: wrote.append(dict(r)))
    assert tcol.stamp("s3", "t1", False) == 3
    assert len(wrote) == 3
    assert all(r["outside_label"] is False for r in wrote)
    # a second settle of the same step writes nothing
    assert tcol.stamp("s3", "t1", True) == 0
    assert len(wrote) == 3


def test_unsettled_row_is_swept_with_no_label():
    wrote: list = []
    tcol.defer(_row("s4"), lambda r: wrote.append(dict(r)))
    assert tcol.sweep() == 1
    assert wrote and "outside_label" not in wrote[0]
    assert tcol.stats()["pending_rows"] == 0
    assert tcol.stats()["flushed_unsettled"] == 1


def test_non_decided_rows_pass_through():
    shadow = {"consumer_id": "tool_choice", "route": "shadow",
              "brain_choice": "run_command", "chosen": "read_file"}
    assert tcol.defer(shadow, lambda r: None) is False
    assert tcol.defer(_row(outcome="finished"), lambda r: None) is False
    assert tcol.defer(_row(outcome="overridden"), lambda r: None) is False
    assert tcol.defer(_row(step=None), lambda r: None) is False


def test_row_after_settle_is_labelled_immediately():
    wrote: list = []
    assert tcol.stamp("s5", "t1", True) == 0
    assert tcol.defer(_row("s5"), lambda r: wrote.append(dict(r))) is True
    assert wrote[0]["outside_label"] is True
    assert wrote[0]["label_reference"] == "step_completed"
    # the retry verdict travels the same reverse path
    assert tcol.stamp("s6", "t1", False) == 0
    assert tcol.defer(_row("s6"), lambda r: wrote.append(dict(r))) is True
    assert wrote[1]["outside_label"] is False


def test_pending_is_bounded(monkeypatch):
    monkeypatch.setattr(tcol, "_MAX_PENDING_ROWS", 2)
    for i in range(3):
        tcol.defer(_row(f"s{i}"), lambda r: None)
    st = tcol.stats()
    assert st["pending_rows"] <= 2
    assert st["dropped_overflow"] >= 1
