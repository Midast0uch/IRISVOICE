"""browser_next's honest label: the sampled rung (2026-11-10, owner).

Parity with the tool model's element can never show which click was right
(agreement 6 of 14 rows on this engine). On a bounded share of clicks the
ORACLE'S element is clicked and the turn verdict labels that choice.

Each guard FAILS on the old module: it had no sampled_pick, and browser_next
was not in the sampled tier.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.agent import browser_next_shadow as bn
from backend.agent import decision_engine as de
from backend.agent import turn_verdict_label as tvl
from scripts.calibrate_decision_threshold import decision_label

PAGE = ("Title: Python docs\nURL: https://docs.python.org/3/\n"
        "Elements (pass the number as element_id to browser_act):\n"
        "[3] Sign in\n[7] Library reference\n[9] Downloads\n")


class _Engine:
    model_id = "d1-test"

    def __init__(self, chosen):
        self.chosen = chosen

    def decide(self, consumer, options, frame):
        assert consumer == "browser_next" and options == ["3", "7", "9"]
        assert "Library reference" in frame["option_criteria"].values()
        return SimpleNamespace(chosen=self.chosen, confidence=0.88,
                               engine_latency_ms=6, distribution=())


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    tvl.reset()
    rows: list = []
    monkeypatch.setattr(bn, "_scope_now", lambda: {"turn_id": "t-b1", "step_id": "s1"})
    monkeypatch.setattr(bn, "emit_row", rows.append)
    yield rows
    tvl.reset()


def test_browser_next_is_in_the_sampled_tier():
    assert "browser_next" in de.TIER_SAMPLABLE


def test_a_sampled_click_uses_the_oracles_element_and_waits_for_the_verdict(monkeypatch, _wire):
    monkeypatch.setattr(de, "sampled_consult_ok", lambda c, k: True)
    pick = bn.sampled_pick(goal="open the library reference", page_text=PAGE,
                           element_id=3, engine=_Engine("7"))
    assert pick == "7"
    assert _wire == [], "held for the turn verdict"
    assert tvl.report_verdict("t-b1", passed=True) == 1
    (row,) = _wire
    assert row["route"] == "sampled" and row["brain_choice"] == "3"
    assert row["outside_label"] == "7" and decision_label(None, {}, row) is True


def test_a_failed_turn_scores_the_click_wrong(monkeypatch, _wire):
    monkeypatch.setattr(de, "sampled_consult_ok", lambda c, k: True)
    bn.sampled_pick(goal="g", page_text=PAGE, element_id=3, engine=_Engine("9"))
    tvl.report_verdict("t-b1", passed=False)
    assert decision_label(None, {}, _wire[0]) is False


def test_an_unsampled_click_stands(monkeypatch, _wire):
    monkeypatch.setattr(de, "sampled_consult_ok", lambda c, k: False)
    assert bn.sampled_pick(goal="g", page_text=PAGE, element_id=3,
                           engine=_Engine("7")) is None
    assert _wire == []


def test_a_click_off_the_page_list_stands(monkeypatch, _wire):
    monkeypatch.setattr(de, "sampled_consult_ok", lambda c, k: True)
    assert bn.sampled_pick(goal="g", page_text=PAGE, element_id=42,
                           engine=_Engine("7")) is None
