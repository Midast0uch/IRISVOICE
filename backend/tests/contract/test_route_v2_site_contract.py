"""route_v2 has a decision site (2026-11-10, owner: "make sure there is code
that acts on its answer").

At the turn-route fork the Oracle's route ("direct" = answer from what is
known, "der" = plan and run tool steps) acts when the bar lets it decide, or
on the sampled rung's bounded share of turns. A sampled row is held for the
turn verdict and scored by name - the outcome label its parity bar lacked.

Each guard FAILS on the old kernel: it had no _route_v2_route and only ever
shadowed the route.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.agent import decision_engine as de
from backend.agent import turn_verdict_label as tvl
from backend.agent.agent_kernel import AgentKernel
from scripts.calibrate_decision_threshold import decision_label


class _Engine:
    model_id = "d1-test"

    def __init__(self, chosen: str) -> None:
        self.chosen = chosen
        self.asked = []

    def decide(self, consumer, options, frame):
        self.asked.append((consumer, tuple(options), frame))
        return SimpleNamespace(chosen=self.chosen, confidence=0.91, engine_latency_ms=4)


def _kernel(rows: list):
    return SimpleNamespace(
        _web_mode_on=lambda: False,
        _shadow_row_sink=rows.append,
        _route_v2_frame=AgentKernel._route_v2_frame,
    )


@pytest.fixture(autouse=True)
def _clean():
    tvl.reset()
    yield
    tvl.reset()


def _wire(monkeypatch, engine, *, sampled: bool, enforced: bool = False):
    monkeypatch.setattr(de, "decides", lambda c: 0.6 if enforced else None)
    monkeypatch.setattr(de, "oracle_acts", lambda c, conf: True)
    monkeypatch.setattr(de, "sampled_consult_ok", lambda c, k: sampled)
    monkeypatch.setattr(de, "get_decision_engine", lambda: engine)


def test_route_v2_is_sampled_and_has_a_site():
    assert "route_v2" in de.TIER_SAMPLABLE
    assert "route_v2" not in de.NO_DECISION_SITE


def test_a_sampled_direct_route_skips_planning_and_waits_for_the_verdict(monkeypatch):
    rows: list = []
    eng = _Engine("direct")
    _wire(monkeypatch, eng, sampled=True)
    out = AgentKernel._route_v2_route(_kernel(rows), "what is a hash map?", "t-r1", True)
    assert out is False, "the Oracle's 'direct' overrides the gate's plan"
    assert rows == [], "the row waits for the turn verdict"
    assert eng.asked and eng.asked[0][1] == ("direct", "der")
    assert tvl.report_verdict("t-r1", passed=True) == 1
    (row,) = rows
    assert row["route"] == "sampled" and row["brain_choice"] == "der"
    assert row["outside_label"] == "direct" and decision_label(None, {}, row) is True


def test_a_failed_turn_scores_the_route_wrong(monkeypatch):
    rows: list = []
    _wire(monkeypatch, _Engine("der"), sampled=True)
    assert AgentKernel._route_v2_route(_kernel(rows), "fix the bug", "t-r2", False) is True
    tvl.report_verdict("t-r2", passed=False)
    assert decision_label(None, {}, rows[0]) is False


def test_an_unsampled_turn_keeps_the_gate(monkeypatch):
    rows: list = []
    eng = _Engine("direct")
    _wire(monkeypatch, eng, sampled=False)
    assert AgentKernel._route_v2_route(_kernel(rows), "hi", "t-r3", True) is None
    assert eng.asked == [] and rows == []


def test_an_unlabelled_sampled_row_is_never_scored_right():
    row = de.sampled_row("route_v2", "direct", 0.9, label_source="outcome")
    assert decision_label(None, {}, row) is None
