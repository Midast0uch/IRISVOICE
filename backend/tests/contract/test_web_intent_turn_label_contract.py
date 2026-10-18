"""Contract: the web_intent TURN-OUTCOME label (web_intent/v2, oracle.md 7.5).

Why it exists (measured live 2026-10-17, data/memory.db): the v1 reference was
the keyword list - a noisy rule that misses requests naming a URL. At 266
distinct rows the consumer sat at oof AUROC 0.4909 with 88% "no" references,
and many Oracle "yes" answers scored wrong were RIGHT.

The honest label is WHAT THE TURN NEEDED, joined at turn grade:
  truth = "yes" when the request names a URL (by rule - the keyword list's
          blind spot stops being label noise), else
  truth = "yes" when the turn ran a web tool that succeeded and passed,
  truth = "no"  when the turn answered without the web and passed,
  no label when the turn failed (the row keeps its parity reference).

These tests pin the safety properties:
  - a row with no turn_id is emitted immediately (no join key -> parity only);
  - nothing here can block a consult or a turn (never raises);
  - parity and outcome stay SEPARATE (label_source says which curve);
  - the pending map is bounded and the drop is counted.
"""
from __future__ import annotations

import pytest

from backend.agent import explorer as ex


@pytest.fixture(autouse=True)
def _clean():
    ex.reset_web_intent_pending()
    yield
    ex.reset_web_intent_pending()


def _row(turn="t1", chosen="yes"):
    return {
        "consumer_id": "web_intent",
        "chosen": chosen,
        "brain_choice": "no",
        "confidence": 0.8,
        "shadow": True,
        "criteria_version": "web_intent/v2",
        "turn_id": turn,
    }


# â”€â”€ the label itself â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_a_url_request_is_yes_by_rule():
    """The keyword list's blind spot: a request naming a URL NEEDED the web,
    whatever the turn did - so its label is yes by rule, never noise."""
    written = []
    ex.set_row_sink(written.append)
    ex.defer_web_intent_row(_row(), "Open https://example.com/data and read it")
    assert ex.resolve_web_intent_turn("t1", passed=False, web_used=False) == 1
    assert written[0]["outside_label"] == "yes"
    assert written[0]["label_source"] == "outcome"


def test_a_passing_turn_that_used_the_web_is_yes():
    written = []
    ex.set_row_sink(written.append)
    ex.defer_web_intent_row(_row(), "find the recent repo of the math")
    assert ex.resolve_web_intent_turn("t1", passed=True, web_used=True) == 1
    assert written[0]["outside_label"] == "yes"


def test_a_passing_turn_without_the_web_is_no():
    written = []
    ex.set_row_sink(written.append)
    ex.defer_web_intent_row(_row(chosen="no"), "what is a binary search")
    assert ex.resolve_web_intent_turn("t1", passed=True, web_used=False) == 1
    assert written[0]["outside_label"] == "no"


def test_a_failed_turn_gets_no_label_and_keeps_parity():
    """A failed turn says nothing about whether the web was needed. The row is
    still EMITTED (a real measurement on its parity reference); only the
    outcome keys are absent."""
    written = []
    ex.set_row_sink(written.append)
    ex.defer_web_intent_row(_row(), "find the recent repo of the math")
    assert ex.resolve_web_intent_turn("t1", passed=False, web_used=False) == 0
    assert len(written) == 1
    assert "outside_label" not in written[0]
    assert "label_source" not in written[0]
    assert written[0]["brain_choice"] == "no"  # the parity pair is intact


def test_the_url_rule_wins_over_a_passing_no_web_turn():
    """A URL request answered from memory still NEEDED the web in principle:
    the rule labels yes so the keyword blind spot cannot punish a correct
    Oracle 'yes'."""
    written = []
    ex.set_row_sink(written.append)
    ex.defer_web_intent_row(_row(), "check www.example.com/docs but cache first")
    ex.resolve_web_intent_turn("t1", passed=True, web_used=False)
    ex.set_row_sink(None)
    assert written[0]["outside_label"] == "yes"


# â”€â”€ the join and the emission â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_a_row_without_a_turn_id_is_emitted_immediately():
    """No join key -> parity is the only reference available. Holding it would
    strand it."""
    written = []
    ex.set_row_sink(written.append)
    ex.defer_web_intent_row(_row(turn=""), "any goal")
    ex.set_row_sink(None)
    assert written, "emitted now, not held"
    assert ex.web_intent_pending_stats()["rows_pending"] == 0


def test_resolve_emits_every_held_row_exactly_once():
    """The kernel asks about the same goal up to twice a turn; every held row
    is emitted, and a second resolve for the same turn is empty."""
    written = []
    ex.set_row_sink(written.append)
    ex.defer_web_intent_row(_row(chosen="yes"), "find the repo")
    ex.defer_web_intent_row(_row(chosen="no"), "find the repo")
    assert ex.resolve_web_intent_turn("t1", True, True) == 2
    assert len(written) == 2
    assert ex.resolve_web_intent_turn("t1", True, True) == 0
    assert len(written) == 2


def test_resolve_only_touches_its_own_turn():
    ex.defer_web_intent_row(_row(turn="t1"), "g1")
    ex.defer_web_intent_row(_row(turn="t2"), "g2")
    ex.resolve_web_intent_turn("t1", True, False)
    st = ex.web_intent_pending_stats()
    assert st["turns_pending"] == 1 and st["rows_pending"] == 1


# â”€â”€ bounded, and the drop is counted â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_the_pending_map_is_bounded_and_counts_its_drops():
    for i in range(ex._WEB_PENDING_CAP + 5):
        ex.defer_web_intent_row(_row(turn=f"t{i}"), "g")
    st = ex.web_intent_pending_stats()
    assert st["turns_pending"] <= ex._WEB_PENDING_CAP
    assert st["dropped_overflow"] >= 5


# â”€â”€ never raises â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@pytest.mark.parametrize("bad", [None, 0, "", [], {}, object()])
def test_defer_never_raises(bad):
    ex.defer_web_intent_row(bad, "g")


@pytest.mark.parametrize("bad", [None, 0, "", [], {}])
def test_resolve_never_raises(bad):
    ex.resolve_web_intent_turn(bad, bad, bad)


def test_a_sink_failure_never_raises():
    def _boom(_row):
        raise RuntimeError("sink down")

    ex.set_row_sink(_boom)
    ex.defer_web_intent_row(_row(), "find the repo")
    assert ex.resolve_web_intent_turn("t1", True, True) == 1
    ex.set_row_sink(None)
