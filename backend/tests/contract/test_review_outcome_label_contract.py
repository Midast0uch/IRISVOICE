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

def test_a_verified_step_makes_refine_wrong(monkeypatch):
    """`refine` is the MOST COMMON verdict (2204 of 2881 live rows). An earlier
    incomplete map left it unstamped under VERIFIED, so nearly every row fell
    through and the label never landed."""
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    row = _row(chosen="refine", brain="pass")
    rol.register(row)
    assert rol.stamp("s1", "VERIFIED") == 1
    assert row["outside_label"] is False


def test_a_verified_step_makes_veto_wrong(monkeypatch):
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    row = _row(chosen="veto", brain="pass")
    rol.register(row)
    assert rol.stamp("s1", "VERIFIED") == 1
    assert row["outside_label"] is False


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
    review row already guards against for parse failures.

    The row is still EMITTED (it is a real measurement on its parity
    reference); only the outcome keys are absent. Dropping it would lose
    evidence."""
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    row = _row()
    written = []
    assert rol.defer(row, written.append) is True
    assert rol.stamp("s1", "UNVERIFIED") == 1
    assert "outside_label" not in row
    assert "label_source" not in row
    assert written == [row]  # emitted, not dropped


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
    """A row with no verdict name at all: emitted unstamped, never stamped."""
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    row = {"consumer_id": "review_verdict", "step_id": "s1", "shadow": True}
    written = []
    assert rol.defer(row, written.append) is True
    assert rol.stamp("s1", "VERIFIED") == 1
    assert "outside_label" not in row
    assert written == [row]


def test_the_deferred_row_is_written_only_after_the_stamp(monkeypatch):
    """THE regression this module exists to prevent: the single writer copies
    the row (`meta = dict(row)`), so writing first and stamping after would
    silently lose the label forever."""
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    row = _row(chosen="pass", brain="pass")
    written = []
    assert rol.defer(row, written.append) is True
    assert written == [], "the row must NOT be written before the step settles"
    assert rol.stamp("s1", "FAILED") == 1
    assert len(written) == 1
    assert written[0]["outside_label"] is False


def test_flag_off_does_not_defer(monkeypatch):
    """With the flag off the caller writes immediately, exactly as before."""
    row = _row()
    written = []
    assert rol.defer(row, written.append) is False
    assert written == []


def test_a_row_with_no_step_id_is_not_deferred(monkeypatch):
    """No join key -> write it now on parity; deferring would strand it."""
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    row = _row(step="")
    assert rol.defer(row, lambda r: None) is False


def test_sweep_flushes_rows_whose_step_never_settled(monkeypatch):
    """A turn that ends early must not lose the measurement."""
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    a, b = _row(step="a"), _row(step="b")
    written = []
    rol.defer(a, written.append)
    rol.defer(b, written.append)
    assert rol.sweep() == 2
    assert len(written) == 2


def test_the_flush_writer_is_NOT_re_deferred(monkeypatch):
    """THE bug that hid the whole feature (measured live: 263 review_verdict
    decisions in the last 2000 rows and the stored total never moved).

    The held row is handed back to the SAME writer, which calls `defer` again -
    so without a re-entrancy guard the flush re-holds the row forever and the
    measurement is never written. This models the real kernel sink:
    `defer(row, write)` then `write(row)` -> must reach the store."""
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    store = []

    def kernel_sink(row):
        # the real _shadow_row_sink defers first, then writes
        if rol.defer(row, kernel_sink):
            return
        store.append(row)

    row = _row(chosen="pass", brain="pass")
    assert kernel_sink(row) is None
    assert store == [], "held until the step settles"
    assert rol.stamp("s1", "VERIFIED") == 1
    assert len(store) == 1, "the flush must actually write, not re-defer"
    assert store[0]["outside_label"] is True


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


# ── the REVERSE path: the step settles BEFORE the row is built ──────────────
#
# Measured live 2026-10-16: a coding run logged "flushed unsettled review rows
# = 5". The cause is a RACE, not a missing join key. The row is built on
# lane("oracle_shadow") - der_loop._shadow_review_verdict submits `_job`, and
# `_job` calls this module's sink on a WORKER thread - while `stamp` runs on the
# turn thread in `_der_finalize_step`. The settle can win. Before the fix such a
# row was held with no step left to settle it, and `sweep` flushed it on PARITY:
# the outcome label was lost and nothing on the row said so.

def test_a_row_arriving_after_the_step_settled_is_still_stamped(monkeypatch):
    """THE RACE. The late row must be stamped ON ARRIVAL, not left to `sweep`."""
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    written = []
    # the step settles first: the lane has not built the row yet
    assert rol.stamp("s7", "FAILED") == 0
    row = _row(step="s7", chosen="pass", brain="pass")
    assert rol.defer(row, written.append) is True
    assert len(written) == 1, "the late row must be WRITTEN, not held"
    assert written[0] is row
    assert row["outside_label"] is False, "FAILED makes `pass` wrong"
    assert row["label_source"] == "outcome"
    assert rol.sweep() == 0, "nothing may be left for sweep"


def test_the_reverse_path_keeps_the_parity_pair(monkeypatch):
    """The recovered row is still a shadow PAIR: the outside label is ADDED, the
    parity reference is not overwritten."""
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    assert rol.stamp("s8", "VERIFIED") == 0
    row = _row(step="s8", chosen="refine", brain="pass")
    rol.defer(row, lambda r: None)
    assert row["brain_choice"] == "pass"
    assert row["chosen"] == "refine"
    assert row["outside_label"] is False  # VERIFIED makes `refine` wrong
    assert row["label_source"] == "outcome"


def test_the_reverse_path_is_counted_and_the_ordinary_path_is_not(monkeypatch):
    """`recovered_after_settle` counts the loss that was SAVED. A row that
    arrives before its step settles is the ordinary order and must not count."""
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    rol.defer(_row(step="s9"), lambda r: None)
    assert rol.stamp("s9", "VERIFIED") == 1
    assert rol.stats()["recovered_after_settle"] == 0
    assert rol.stamp("s10", "VERIFIED") == 0   # settles first
    rol.defer(_row(step="s10"), lambda r: None)
    assert rol.stats()["recovered_after_settle"] == 1


def test_the_settled_memory_is_bounded_and_the_first_settle_wins(monkeypatch):
    """`_SETTLED` must not leak, and a repeat settle must not rewrite the
    outcome already remembered for that id."""
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    for i in range(rol._SETTLED_CAP + 25):
        rol.stamp(f"late{i}", "VERIFIED")
    assert len(rol._SETTLED) <= rol._SETTLED_CAP
    rol.reset()
    rol.stamp("dup", "VERIFIED")
    rol.stamp("dup", "FAILED")  # a second settle must NOT overwrite the first
    row = _row(step="dup", chosen="pass", brain="pass")
    rol.defer(row, lambda r: None)
    assert row["outside_label"] is True  # VERIFIED, not FAILED


def test_an_unverified_late_outcome_still_emits_the_row_unstamped(monkeypatch):
    """No ground truth -> no label, even on the reverse path. The row is a real
    measurement on its parity reference and must not be dropped."""
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    written = []
    assert rol.stamp("s12", "UNVERIFIED") == 0
    row = _row(step="s12")
    assert rol.defer(row, written.append) is True
    assert written == [row]
    assert "outside_label" not in row
    assert "label_source" not in row


def test_sweep_still_flushes_and_counts_a_row_with_no_outcome(monkeypatch):
    """The loss path stays a real path: a row whose step genuinely never settled
    is still written on parity, and the loss is COUNTED."""
    monkeypatch.setenv(rol.ENV_FLAG, "1")
    written = []
    rol.defer(_row(step="never"), written.append)
    assert rol.sweep() == 1
    assert len(written) == 1
    assert "outside_label" not in written[0]
    assert rol.stats()["flushed_parity"] == 1


def test_flag_off_remembers_no_outcome(monkeypatch):
    """Flag off is still a TOTAL no-op: a stamp creates no state at all."""
    assert rol.enabled() is False
    assert rol.stamp("s11", "VERIFIED") == 0
    assert len(rol._SETTLED) == 0
    assert rol.defer(_row(step="s11"), lambda r: None) is False
