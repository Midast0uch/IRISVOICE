"""Behavioural tests: `AgentKernel._needs_thinking` (the phrase-list heuristic).

The `use_thinking` Oracle consumer was REMOVED (owner decision, 2026-10-13: models
think natively). The phrase list is the only answer. The user's explicit
`concise`/`thorough` setting and the social short-circuit are RULES, not
heuristics — they are asserted here so a future edit cannot quietly change them.
"""

from __future__ import annotations

import pytest

from backend.agent import surface_shadow as ss
from backend.agent.agent_kernel import AgentKernel
from backend.agent.decision_engine import Noul


class _Eng:
    def __init__(self, p):
        self._p = p
        self.seen: list = []

    def noul(self, consumer_id, statement, frame, *,
             true_label="yes", false_label="no"):
        self.seen.append(consumer_id)
        return Noul(consumer_id=consumer_id, probability=self._p,
                    engine_latency_ms=2)


def _kernel(style="balanced"):
    k = AgentKernel.__new__(AgentKernel)
    k._thinking_style = style
    return k


@pytest.fixture
def rows():
    captured: list = []
    ss.set_row_sink(captured.append)
    yield captured
    ss.set_row_sink(None)


def _install(monkeypatch, engine):
    monkeypatch.setattr(
        "backend.agent.decision_engine.get_decision_engine", lambda: engine)


class TestUseThinking:
    def test_a_plain_question_still_skips_thinking(self, monkeypatch, rows):
        """A plain question must not turn into a thinking request."""
        _install(monkeypatch, _Eng(p=0.97))
        k = _kernel()
        assert k._needs_thinking("what time is it") is False

    def test_explicit_style_settings_are_rules(self):
        """`concise` / `thorough` are user RULES: they answer whatever the text says."""
        assert _kernel("concise")._needs_thinking("why?") is False
        assert _kernel("thorough")._needs_thinking("hi") is True

    def test_the_social_short_circuit_is_a_rule(self):
        """A short social message is a hard rule, not a phrase-list match."""
        assert _kernel()._needs_thinking("how are you") is False

    def test_a_dead_engine_matches_the_phrase_list_exactly(
        self, monkeypatch, rows,
    ):
        """AC29.7: with the engine dead, every verdict equals the raw list."""
        def _dead():
            raise RuntimeError("engine dead")

        monkeypatch.setattr(
            "backend.agent.decision_engine.get_decision_engine", _dead)
        k = _kernel()

        cases = {
            "why does the sky look blue during the day": True,
            "explain quantum tunnelling in simple terms please": True,
            "debug this traceback and tell me what is wrong": True,
            "what is the capital city of France please tell": False,
            "look up the population of Japan for me now": False,
            "hello there": False,
        }
        for text, expected in cases.items():
            assert k._needs_thinking(text) is expected, text
