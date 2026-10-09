"""Contract: the report MUST NOT blend the two references into one curve.

The owner's concern: "make sure the data we get from copying doesn't interfere
with the data we get from checking". It does not, because a row is scored
against ONE reference (decision_label prefers `outside_label`, falls back to
`brain_choice`) and `label_source` records which. What would break that is the
FITTER pooling both kinds into one isotonic curve - averaging two different
questions produces a number that means nothing.

So: a consumer's rows are grouped by label_source and fitted SEPARATELY. A
consumer holding both kinds reports both, and no single blended number is ever
produced.
"""
from __future__ import annotations

from scripts.consumer_enforcement_report import split_by_reference


def _row(cid, src, conf=0.8, correct=True):
    return {
        "consumer_id": cid,
        "label_source": src,
        "confidence": conf,
        "correct": correct,
    }


def test_rows_split_into_the_two_reference_kinds():
    rows = [
        _row("review_verdict", "incumbent"),
        _row("review_verdict", "outcome"),
        _row("tool_choice", "incumbent"),
    ]
    flat_outcome, incumbent, outcome = split_by_reference(rows)
    # the flat list is the outcome rows, ready to report on their own
    assert [r["label_source"] for r in flat_outcome] == ["outcome"]
    # grouped per consumer, so each kind can be fitted on its own curve
    assert set(incumbent) == {"review_verdict", "tool_choice"}
    assert len(incumbent["review_verdict"]) == 1
    assert set(outcome) == {"review_verdict"}
    assert len(outcome["review_verdict"]) == 1


def test_a_row_with_no_label_source_is_parity():
    """Pre-REQ-7 rows carried no label_source; they are incumbent-reference."""
    rows = [{"consumer_id": "x", "confidence": 0.5, "correct": True}]
    _, incumbent, outcome = split_by_reference(rows)
    assert len(incumbent["x"]) == 1
    assert outcome == {}


def test_an_outcome_row_is_never_treated_as_parity():
    rows = [_row("c", "outcome")]
    _, incumbent, outcome = split_by_reference(rows)
    assert incumbent == {}
    assert len(outcome["c"]) == 1


def test_two_consumers_do_not_mix():
    rows = [
        _row("a", "incumbent"), _row("a", "outcome"),
        _row("b", "incumbent"),
    ]
    _, incumbent, outcome = split_by_reference(rows)
    assert len(incumbent["a"]) == 1
    assert len(outcome["a"]) == 1
    assert "a" not in outcome or not outcome.get("b")
    assert len(incumbent["b"]) == 1


def test_empty_input_is_safe():
    flat, incumbent, outcome = split_by_reference([])
    assert flat == [] and incumbent == {} and outcome == {}