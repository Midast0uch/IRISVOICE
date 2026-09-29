"""Behavioural tests: engine-unavailable parity at all four surface sites
(REQ-29 AC29.7, T46–T49).

AC29.7 — WHEN the engine is unavailable THEN every one of these sites SHALL
behave exactly as today.

This is the regression guard for the whole wave: the four sites are shadow
observers, so a dead engine must leave every decision byte-identical. The
comparison is made against the SAME call with no engine argument at all.
"""

from __future__ import annotations

import pytest

from backend.agent import surface_shadow as ss
from backend.agent.agent_kernel import AgentKernel
from backend.agent.tool_decision import _goal_needs_action


@pytest.fixture
def dead_engine(monkeypatch):
    """An engine whose resolution raises — the 'unavailable' case."""
    def _dead():
        raise RuntimeError("engine dead")

    monkeypatch.setattr(
        "backend.agent.decision_engine.get_decision_engine", _dead)
    return _dead


@pytest.fixture
def rows():
    captured: list = []
    ss.set_row_sink(captured.append)
    yield captured
    ss.set_row_sink(None)


def _kernel(style="balanced"):
    k = AgentKernel.__new__(AgentKernel)
    k._thinking_style = style
    return k


# The batteries each site is measured on, chosen so both answers appear.
_NEEDS_ACTION = [
    "search for the latest merger news",
    "look up the population of Japan",
    "ponder the meaning of it all",
    "write a file with the results",
    "",
]
_THINKING = [
    "why does the sky look blue during the day",
    "explain quantum tunnelling in simple terms please",
    "debug this traceback and tell me what is wrong",
    "what is the capital city of France please tell",
    "look up the population of Japan for me now",
    "hello there",
]


class TestAllFourSitesUnchangedWhenDead:
    def test_all_four_sites_unchanged_when_dead(self, dead_engine, rows):
        """AC29.7: all four sites return the legacy verdict with no engine."""
        # ── site 1: needs_action (the NONE gate) ───────────────────────────
        # The documented lexical answers, unchanged by a dead engine.
        assert _goal_needs_action("search for the latest merger news") is True
        assert _goal_needs_action("look up the population of Japan") is True
        assert _goal_needs_action("ponder the meaning of it all") is False
        assert _goal_needs_action("") is False

        # ── site 2: use_thinking ───────────────────────────────────────────
        k = _kernel()
        for text in _THINKING:
            assert isinstance(k._needs_thinking(text), bool), text
        assert k._needs_thinking(
            "why does the sky look blue during the day") is True
        assert k._needs_thinking("what time is it") is False

        # ── sites 3 & 4: the two surface_bool consumers ────────────────────
        # With no engine the legacy decider's value passes through untouched.
        for cid in ("escalate_incomplete", "has_gaps"):
            for legacy in (True, False):
                value, row = ss.surface_bool(
                    cid, "some step result",
                    brain_bool_fn=lambda v=legacy: v,
                    engine=ss.AUTO_ENGINE,
                )
                assert value is legacy, (cid, legacy)
                assert row is None, (
                    f"{cid} fabricated a row with no engine — a shadow must "
                    "never invent data"
                )

        assert rows == [], (
            "a dead engine emitted shadow rows — the sites are not inert "
            "(AC29.7)"
        )

    def test_every_site_is_opt_in_on_the_engine(self, dead_engine):
        """`engine=None` means NO ENGINE: the shadow must not adopt the
        singleton implicitly, or a unit test would load a 642MB model."""
        for cid in ("has_gaps", "use_thinking", "escalate_incomplete",
                    "needs_action"):
            assert ss.score_surface_bool(cid, "x", engine=None) is None, cid

    def test_the_surface_bool_helper_is_fail_safe(self, dead_engine):
        """A raising legacy decider returns the conservative False, not an
        exception — these run on the reply and step paths."""
        def _boom():
            raise ValueError("decider exploded")

        for cid in ("has_gaps", "use_thinking", "escalate_incomplete",
                    "needs_action"):
            value, row = ss.surface_bool(
                cid, "x", brain_bool_fn=_boom, engine=ss.AUTO_ENGINE)
            assert value is False
            assert row is None
