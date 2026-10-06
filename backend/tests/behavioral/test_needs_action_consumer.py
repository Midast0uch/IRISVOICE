"""Behavioural tests: the `needs_action` consumer (REQ-29 AC29.4, T49).

AC29.4 — a `needs_action` consumer shadowing the NONE-gate heuristics,
preserving their documented SAFE direction (when in doubt, act).

`_goal_needs_action` gates the engine's OWN `NONE` commit (OQ-2). Its
false-positive direction is the safe one: returning True keeps the old escalate
path. The engine may therefore ADD a True but may never REMOVE one — a model
false negative must not be able to stop a step that needs a tool.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.agent import surface_shadow as ss
from backend.agent.decision_engine import Noul
from backend.agent.tool_decision import _goal_needs_action


class _Eng:
    def __init__(self, p):
        self._p = p
        self.seen: list = []

    def noul(self, consumer_id, statement, frame, *,
             true_label="yes", false_label="no"):
        self.seen.append(consumer_id)
        return Noul(consumer_id=consumer_id, probability=self._p,
                    engine_latency_ms=2)


@pytest.fixture
def rows():
    captured: list = []
    ss.set_row_sink(captured.append)
    yield captured
    ss.set_row_sink(None)


def _install(monkeypatch, engine):
    monkeypatch.setattr(
        "backend.agent.decision_engine.get_decision_engine", lambda: engine)


class TestNeedsActionSafeDirection:
    def test_safe_direction_preserved(self, monkeypatch, rows):
        """AC29.4: the engine may ADD a True, never REMOVE one."""
        # The lexical heuristic says ACT (a search goal). The engine says the
        # OPPOSITE with high confidence — the safe direction must win.
        engine = _Eng(p=0.02)
        _install(monkeypatch, engine)

        assert _goal_needs_action("search for the latest merger news") is True, (
            "a confident engine NEGATIVE narrowed the safe direction — a step "
            "that needs a tool could now be stopped (AC29.4)"
        )
        # CHANGED (2026-10-05, Oracle Stage B, owner-approved): a lexical True is
        # final - the engine can only WIDEN it - so it is no longer scored at all
        # (one reply-path Oracle call saved). This used to assert the consumer was
        # scored and a row written for a lexical-True goal. The calibration rows
        # for this consumer now come from lexical-False goals only, scored on the
        # lane (see test_oracle_enforcement_contract).
        assert engine.seen == [], "a lexical True was scored although it is final"
        assert rows == []

    def test_the_engine_may_widen_toward_action_when_enforced(
        self, monkeypatch, rows,
    ):
        """AC29.4: the WIDENING half of the safe direction.

        In shadow the engine is ignored entirely (the site is unchanged), so
        the widening property is asserted where it is observable: an ENFORCED
        confident positive yields True. The site keeps shadow until a TG-13
        measured bar, which is why the next test pins that it is still shadow.
        """
        value, row = ss.surface_bool(
            "needs_action", "ponder the meaning of it all",
            brain_bool_fn=lambda: False,
            engine=_Eng(p=0.99), enforced=True,
        )
        assert value is True, (
            "an enforced confident POSITIVE did not widen toward the safe "
            "action direction"
        )
        assert row["brain_bool"] is True

    def test_the_site_is_still_shadow(self):
        """Foundation rule (D7): the site must not be enforcing yet."""
        src = (
            Path(__file__).resolve().parents[3]
            / "backend" / "agent" / "tool_decision.py"
        ).read_text(encoding="utf-8", errors="replace")
        site = src.split('"needs_action"')[1][:400]
        assert "enforced=True" not in site, (
            "the needs_action site flipped to enforced in a shadow wave"
        )

    def test_the_engine_may_not_narrow_the_safe_direction(
        self, monkeypatch, rows,
    ):
        """AC29.4, the half that must hold even AFTER a flip: with the engine
        enforced and confidently negative, a lexical True still wins."""
        engine = _Eng(p=0.01)
        _install(monkeypatch, engine)

        assert _goal_needs_action("search for the latest merger news") is True

    def test_engine_unavailable_is_byte_identical(self, monkeypatch, rows):
        """AC29.7: with no engine, the lexical heuristic is the answer."""
        def _dead():
            raise RuntimeError("engine dead")

        monkeypatch.setattr(
            "backend.agent.decision_engine.get_decision_engine", _dead)

        cases = {
            "search for the latest merger news": True,
            "look up the population of Japan": True,
            "ponder the meaning of it all": False,
            "": False,
        }
        for goal, expected in cases.items():
            assert _goal_needs_action(goal) is expected, goal
        assert rows == [], "a dead engine must not fabricate a row"

    def test_an_empty_goal_is_never_scored(self, monkeypatch, rows):
        """The empty-goal early return is unchanged — no engine call, no row."""
        engine = _Eng(p=0.99)
        _install(monkeypatch, engine)

        assert _goal_needs_action("") is False
        assert engine.seen == []
        assert rows == []
