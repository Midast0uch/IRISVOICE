"""Behavioural tests: the `use_thinking` consumer (REQ-29 AC29.2, T47).

AC29.2 — a `use_thinking` bool consumer shadowing the phrase list, with the
list retained as the engine-unavailable fallback (AC29.7).

The site is `AgentKernel._needs_thinking` (`agent_kernel.py:2365`; the spec's
`_should_use_thinking` name is stale). The user's explicit `concise`/`thorough`
setting and the social short-circuit are RULES, not heuristics — they are
untouched and are asserted here so a future edit cannot quietly score them.
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
    def test_use_thinking_shadow_and_fallback(self, monkeypatch, rows):
        """AC29.2/AC29.7: shadow scores the phrase-list verdict; with no engine
        the phrase list is the answer, byte-identical to today."""
        # (a) engine available and AGREEING: the phrase list still decides.
        engine = _Eng(p=0.93)
        _install(monkeypatch, engine)
        k = _kernel()

        assert k._needs_thinking(
            "why does the sky look blue during the day") is True
        assert engine.seen == ["use_thinking"]
        assert rows and rows[0]["consumer_id"] == "use_thinking"
        assert rows[0]["brain_bool"] is True

        # (b) engine UNAVAILABLE: the phrase list is the fallback (AC29.7).
        rows.clear()

        def _dead():
            raise RuntimeError("engine dead")

        monkeypatch.setattr(
            "backend.agent.decision_engine.get_decision_engine", _dead)

        assert k._needs_thinking(
            "why does the sky look blue during the day") is True
        assert k._needs_thinking("what time is it") is False
        assert rows == [], "a dead engine must not fabricate a row"

    def test_a_plain_question_still_skips_thinking(self, monkeypatch, rows):
        """The shadow must not turn every message into a thinking request."""
        _install(monkeypatch, _Eng(p=0.97))
        k = _kernel()
        assert k._needs_thinking("what time is it") is False

    def test_explicit_style_settings_are_not_scored(self, monkeypatch, rows):
        """`concise` / `thorough` are user RULES — the engine must not be
        consulted, so no row is produced for them."""
        engine = _Eng(p=0.99)
        _install(monkeypatch, engine)

        assert _kernel("concise")._needs_thinking("why?") is False
        assert _kernel("thorough")._needs_thinking("hi") is True

        assert engine.seen == [], (
            "an explicit user setting was shadow-scored — it is a rule, not a "
            "heuristic to calibrate"
        )
        assert rows == []

    def test_the_social_short_circuit_is_not_scored(self, monkeypatch, rows):
        """A short social message is a hard rule, not a calibration target."""
        engine = _Eng(p=0.99)
        _install(monkeypatch, engine)

        assert _kernel()._needs_thinking("how are you") is False
        assert engine.seen == []
        assert rows == []

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
