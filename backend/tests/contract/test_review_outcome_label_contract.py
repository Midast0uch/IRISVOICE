"""Contract: the review OUTCOME label wrapper (IRIS_ORACLE_REVIEW_OUTCOME).

Why it exists (measured live 2026-10-09, data/memory.db): review_verdict was
scored only against PARITY - did d1 agree with the Brain's reviewer. The Brain
passes ~96% of steps, so a d1 row that correctly catches a bad step is scored
WRONG for disagreeing. Measured 42/143 correct, AUROC 0.375 (worse than
random). The loop already knows the truth: `_der_finalize_step` computes
`verified_label` (VERIFIED/UNVERIFIED/FAILED) for the same step.

The row is written at REVIEW time and the step settles LATER, so the outcome
must be deferred and attached to the same row.

These tests pin the safety properties the owner asked for:
  - the flag OFF is a total no-op (byte-identical behaviour to 0bdd1ad1);
  - nothing here can block a step (never raises, whatever it is handed);
  - parity and outcome stay SEPARATE, never blended.
"""
from __future__ import annotations

import pytest

from backend.agent import review_outcome_label as rol


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    rol.reset()
    monkeypatch.delenv(rol.ENV_FLAG, raising=False)
    yield
    rol.reset()


def _row(step="s1", chosen="pass", brain="pass"):
    return {
        "consumer_id": "review_verdict",
        "chosen": chosen,
        "brain_choice": brain,
        "shadow": True,
        "step_id": step,
    }


# ── the flag is the safety mechanism ────────────────────────────────────────

def test_flag_off_registers_nothing():
    assert rol.enabled() is False
    assert rol.register(_row()) is None
    assert rol.stamp("s1", "VERIFIED") == 0


def test_flag_off_leaves_a_row_byte_identical():
    """The owner's requirement: flag off == the behaviour at 0bdd1ad1."""
    row = _row()
    before = dict(row)
    rol.register(row)
    rol.stamp("s1", "VERIFIED")
    assert row == before
    assert "outside_label" not in row


def test_flag_on_is_opt_in_per_value():
    for v in ("1", "true", "yes", "on"):
        rol.reset()
        import os

        os.environ[rol.ENV_FLAG] = v
        assert rol.enabled() is True, v


def test_flag_off_for_the_explicit_off_values(monkeypatch):
    for v in ("", "0", "false", "False"):
        monkeypatch.setenv(rol.ENV_FLAG, v)
        assert rol.enabled() is False, v


# ── the label itself ────────────────────────────────────────────────────────

def test_a_verified_step_makes_pass_correct(monkeypatch):
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    row = _row(chosen="pass", brain="pass")
    assert rol.register(row) == "s1"
    assert rol.stamp("s1", "VERIFIED") == 1
    assert row["outside_label"] is True
    assert row["label_source"] == "outcome"


def test_a_failed_step_makes_pass_wrong(monkeypatch):
    """The case parity CANNOT see: d1 and the Brain agreed the step was fine,
    and it turned out not to be."""
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    row = _row(chosen="pass", brain="pass")
    rol.register(row)
    rol.stamp("s1", "FAILED")
    assert row["outside_label"] is False


def test_a_failed_step_makes_veto_right(monkeypatch):
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    row = _row(chosen="veto", brain="pass")
    rol.register(row)
    rol.stamp("s1", "FAILED")
    assert row["outside_label"] is True


def test_an_unverified_step_stamps_nothing(monkeypatch):
    """No ground truth -> no label. Guessing would be the phantom agreement the
    review row already guards against for parse failures."""
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    row = _row()
    rol.register(row)
    assert rol.stamp("s1", "UNVERIFIED") == 0
    assert "outside_label" not in row
    assert "label_source" not in row


def test_an_unknown_verified_label_stamps_nothing(monkeypatch):
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    row = _row()
    rol.register(row)
    assert rol.stamp("s1", "BANANA") == 0
    assert "outside_label" not in row


def test_a_stamp_without_a_registered_row_is_a_no_op(monkeypatch):
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    assert rol.stamp("never-registered", "VERIFIED") == 0


def test_a_step_settles_twice_stamps_once(monkeypatch):
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    row = _row()
    rol.register(row)
    assert rol.stamp("s1", "VERIFIED") == 1
    assert rol.stamp("s1", "FAILED") == 0
    assert row["outside_label"] is True  # first stamp wins, no double-write


# ── only review rows are held ───────────────────────────────────────────────

def test_another_consumer_is_ignored(monkeypatch):
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    row = {"consumer_id": "tool_choice", "chosen": "x", "step_id": "s1"}
    assert rol.register(row) is None
    assert rol.stamp("s1", "VERIFIED") == 0


def test_a_row_without_a_step_id_is_not_held(monkeypatch):
    """No join key -> parity is the only reference available. Holding it would
    risk attaching one step's outcome to another's row."""
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    assert rol.register(_row(step="")) is None


def test_the_caller_supplied_step_id_is_used_and_stamped_onto_the_row(monkeypatch):
    """MEASURED DEFECT: 2877/2877 live review_verdict rows carried an EMPTY
    step_id - the review site's scope contextvar binds turn_id only - so the
    join had no key and nothing could ever be stamped. The caller knows the
    item, so it passes the id explicitly."""
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    row = _row(step="")
    assert rol.register(row, "s42") == "s42"
    assert row["step_id"] == "s42"      # the row carries the join key to the ledger
    assert rol.stamp("s42", "VERIFIED") == 1
    assert row["outside_label"] is True


def test_a_row_step_id_wins_over_the_supplied_one(monkeypatch):
    """A row that already carries its own scope keeps it."""
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    row = _row(step="own")
    assert rol.register(row, "other") == "own"
    assert rol.stamp("own", "VERIFIED") == 1
    assert rol.stamp("other", "FAILED") == 0


# ── never blocks a step ─────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [None, 0, "", [], {}, object()])
def test_register_never_raises(bad):
    rol.register(bad)


@pytest.mark.parametrize("bad", [None, 0, "", [], {}])
def test_stamp_never_raises(bad, monkeypatch):
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    rol.stamp(bad, bad)


def test_a_missing_outcome_key_never_raises(monkeypatch):
    """A row with no verdict name at all."""
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    row = {"consumer_id": "review_verdict", "step_id": "s1", "shadow": True}
    rol.register(row)
    assert rol.stamp("s1", "VERIFIED") == 0


# ── bounded, and the drop is counted ────────────────────────────────────────

def test_the_pending_map_is_bounded_and_counts_its_drops(monkeypatch):
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    for i in range(rol._CAP + 40):
        rol.register(_row(step=f"s{i}"))
    st = rol.stats()
    assert st["pending"] <= rol._CAP
    assert st["dropped_overflow"] >= 40


# ── parity and outcome stay SEPARATE ────────────────────────────────────────

def test_the_row_keeps_both_references(monkeypatch):
    """The owner's question: we do not have to choose. Both facts survive on the
    one row, and label_source says which one the row is scored on."""
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    row = _row(chosen="refine", brain="pass")
    rol.register(row)
    rol.stamp("s1", "FAILED")
    # the parity pair is intact - agreement stays measurable forever
    assert row["brain_choice"] == "pass"
    assert row["chosen"] == "refine"
    # and the row is now scored against ground truth
    assert row["outside_label"] is False
    assert row["label_source"] == "outcome"