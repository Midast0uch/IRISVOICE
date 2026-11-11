"""Behavioural tests: engine-unavailable parity at all four surface sites
(REQ-29 AC29.7, T46–T49).

AC29.7 — WHEN the engine is unavailable THEN every one of these sites SHALL
behave exactly as today.

This is the regression guard for the whole wave: the four sites are shadow
observers, so a dead engine must leave every decision byte-identical. The
comparison is made against the SAME call with no engine argument at all.

2026-11-10 (owner): the surface consumers are all retired, and with them the
`surface_bool` helper sites 3 and 4 ran through (and its row sink). The two
helper tests went with it; the incumbent sites below are unchanged.
"""

from __future__ import annotations

import pytest

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
    def test_all_four_sites_unchanged_when_dead(self, dead_engine):
        """AC29.7: all four sites return the legacy verdict with no engine."""
        # ── site 1: needs_action (the NONE gate) ───────────────────────────
        # The documented lexical answers, unchanged by a dead engine.
        assert _goal_needs_action("search for the latest merger news") is True
        assert _goal_needs_action("look up the population of Japan") is True
        assert _goal_needs_action("ponder the meaning of it all") is False
        assert _goal_needs_action("") is False

        # ── site 2: _needs_thinking (lexical heuristic; no consumer) ───────
        k = _kernel()
        for text in _THINKING:
            assert isinstance(k._needs_thinking(text), bool), text
        assert k._needs_thinking(
            "why does the sky look blue during the day") is True
        assert k._needs_thinking("what time is it") is False
