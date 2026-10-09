"""Contract: a structurally unscoreable decision row is COUNTED, never scored.

Measured live 2026-10-09 against data/memory.db (d1, 225 tool_choice rows):
  - 24% had the row's reference TRUNCATED OFF the menu the engine scored
    (list_directory x31, write_file x21, search x1). The shadow writer caps the
    menu at candidate_cap minus two reserved control slots, so a tool the Brain
    was OFFERED and then actually called can be cut away. The engine was never
    offered the right answer.
  - 10% chose a CONTROL label (DELEGATE/NONE) while the reference is a sentinel
    in zero rows, so those rows can only ever score WRONG.

Both defects belong to the HARNESS. Scoring them punishes the engine for a
truncation decision it never made. These tests FAIL on the pre-2026-10-09 code,
which returned a bool for both shapes.
"""
from __future__ import annotations

from scripts.calibrate_decision_threshold import (
    _reference_on_menu,
    decision_label,
)


def _row(chosen: str, reference: str, menu: list[str] | None) -> dict:
    return {
        "consumer_id": "tool_choice",
        "engine": "d1-3b-ad-q4_k_m",
        "shadow": True,
        "chosen": chosen,
        "confidence": 0.9,
        "brain_choice": reference,
        "candidates": [{"name": n, "prob": 0.1} for n in (menu or [])],
    }


MENU = ["read_file", "edit_file", "grep_files", "run_command", "DELEGATE", "NONE"]


def test_a_row_whose_reference_was_truncated_off_the_menu_is_not_scored():
    """write_file was never offered; the engine could not have picked it."""
    d = _row("read_file", "write_file", MENU)
    assert _reference_on_menu(d) is False
    assert decision_label("success", {}, d) is None, (
        "a truncated reference must be UNSCOREABLE, not scored wrong"
    )


def test_a_control_label_answer_is_not_scored():
    """The reference is never DELEGATE/NONE, so such a row can only score wrong."""
    d = _row("DELEGATE", "read_file", MENU)
    assert decision_label("success", {}, d) is None


def test_a_genuinely_comparable_row_still_scores():
    """The fix must not silence real evidence."""
    assert decision_label("success", {}, _row("read_file", "read_file", MENU)) is True
    assert decision_label("success", {}, _row("edit_file", "read_file", MENU)) is False


def test_a_row_with_no_menu_is_left_scoreable():
    """The pre-cap era wrote no candidate list; absence proves nothing."""
    d = _row("read_file", "write_file", None)
    assert _reference_on_menu(d) is True
    assert decision_label("success", {}, d) is False


def test_an_outside_label_still_wins_over_the_incumbent():
    """REQ-7 AC7.1 is untouched: the outside label remains first."""
    d = _row("read_file", "edit_file", MENU)
    d["outside_label"] = "read_file"
    assert decision_label("success", {}, d) is True


def test_a_bool_reference_is_unaffected():
    """brain_bool consumers (needs_action, done) keep their parity label."""
    d = {
        "consumer_id": "needs_action", "engine": "x", "shadow": True,
        "chosen": True, "confidence": 0.8, "brain_bool": True,
    }
    assert decision_label("success", {}, d) is True
    d["brain_bool"] = False
    assert decision_label("success", {}, d) is False