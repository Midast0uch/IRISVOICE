"""Contract (specs/reply-surface-contract REQ-15 / REQ-14, task T9 — CT-10 + CT-12).

CT-10: the decision-engine consumer set is
``{tool_choice, presentation (async observer), narration}`` with NO blocking
engine call on the reply path — the ``presentation`` consumer is preserved as
a calibration observer that runs on a daemon thread AFTER the reply is
decided, and its verdict can never steer the live surface.

CT-12: the same reply yields the same surface across repeated runs
``(deterministic — REQ-14 AC4)``: the reply lane depends only on
``show``-presence.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

import backend.agent.decision_engine as de
from backend.agent.agent_kernel import AgentKernel


class _Bus:
    def __init__(self):
        self.events = []

    def emit(self, event, data=None, **kw):
        self.events.append((event, data))


def _kernel(monkeypatch, zone="chat"):
    k = AgentKernel.__new__(AgentKernel)
    k._last_render_emitted = False
    k._last_spoken_text = ""
    monkeypatch.setattr(k, "_pacman_zone_for_turn", lambda: zone, raising=False)
    monkeypatch.setattr(k, "_store_document_data", lambda **kw: None,
                        raising=False)
    bus = _Bus()
    monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: bus)
    return k, bus


class TestConsumerSetIsPinned:
    def test_consumer_set_is_locked(self, monkeypatch):
        """CT-10a: the presentation consumer is PRESERVED (not deleted), and
        only tool_choice is enforced by default (IRIS_DECISION_ENFORCE)."""
        assert set(de.CONSUMERS) == {"tool_choice", "presentation", "narration"}, (
            "the consumer set changed — cross-spec lock with "
            "specs/tool-decision-engine REQ-11"
        )
        monkeypatch.delenv("IRIS_DECISION_ENFORCE", raising=False)
        assert de.enforced_consumers() == frozenset({"tool_choice"}), (
            "default enforcement must stay tool_choice-only; presentation is "
            "an observer"
        )


class _BlockingEngine:
    """Fake engine whose decide() blocks until released and records the
    calling thread — proof of WHERE the consult happens."""

    def __init__(self):
        self.gate = threading.Event()
        self.calls = []

    def decide(self, consumer, options, frame):
        self.calls.append(
            {
                "consumer": consumer,
                "thread": threading.current_thread().name,
                "frame": frame,
            }
        )
        self.gate.wait(timeout=10)
        return None


class TestObserverIsOffTheReplyPath:
    def test_no_blocking_engine_call_on_the_reply_path(self, monkeypatch):
        """CT-10b: a plain reply returns immediately even while the engine
        is mid-decision; the consult lands on the observer thread."""
        engine = _BlockingEngine()
        monkeypatch.setattr(de, "get_decision_engine", lambda: engine)
        k, bus = _kernel(monkeypatch, zone="reference")
        text = "plain reply, no show payload " * 40  # structural-free, long
        started = time.monotonic()
        out = AgentKernel._process_structured_response(
            k, text, turn_id="t-obs", conversation_id="c"
        )
        elapsed = time.monotonic() - started
        assert out == text
        assert bus.events == []
        assert elapsed < 2.0, (
            f"reply path blocked on the engine ({elapsed:.2f}s) — REQ-15 AC1"
        )
        engine.gate.set()
        # Let the observer thread finish; it must be the ONLY engine caller.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not engine.calls:
            time.sleep(0.02)
        assert len(engine.calls) == 1, "observer should consult exactly once"
        call = engine.calls[0]
        assert call["consumer"] == "presentation"
        assert call["thread"] == "iris-surface-observer", (
            f"engine consulted on the reply path ({call['thread']})"
        )

    def test_observer_verdict_never_steers_the_live_surface(self, monkeypatch):
        """CT-10c: even a DECISIVE, ENFORCED presentation verdict cannot
        fabricate a card — REQ-14 AC2 makes show-presence the only trigger."""
        class _DecidingEngine:
            def decide(self, consumer, options, frame):
                class _DS:
                    chosen = "prism_card"
                    confidence = 0.99
                    engine_latency_ms = 0.1

                return _DS()

            model_id = "fake-engine"
            _cfg = type("C", (), {"threshold_for": lambda self, c: 0.5})()

        engine = _DecidingEngine()
        monkeypatch.setattr(de, "get_decision_engine", lambda: engine)
        # Force presentation into the enforced set — the strongest possible
        # observer configuration.
        monkeypatch.setenv("IRIS_DECISION_ENFORCE", "tool_choice,presentation")
        k, bus = _kernel(monkeypatch, zone="reference")
        text = "a plain reply that an over-eager engine would card-ify"
        out = AgentKernel._process_structured_response(
            k, text, turn_id="t-obs2", conversation_id="c"
        )
        assert out == text, "observer verdict steered the live surface"
        assert bus.events == [], "observer fabricated a card"
        assert k._last_render_emitted is False


class TestDeterministicSurface:
    def test_same_reply_same_surface_repeated(self, monkeypatch):
        """CT-12: identical inputs produce identical surfaces (REQ-14 AC4)."""
        replies = [
            "short plain answer",
            "# Plan\n\n| a | b |\n|---|---|\n| 1 | 2 |\n" * 30,  # long structural plain
            json.dumps({
                "speak": "s",
                "show": {"format": "markdown", "content": "doc"},
            }),
        ]
        for text in replies:
            outcomes = []
            for _ in range(3):
                k, bus = _kernel(monkeypatch, zone="reference")
                out = AgentKernel._process_structured_response(
                    k, text, turn_id="t-det", conversation_id="c"
                )
                outcomes.append((out, len(bus.events), k._last_render_emitted))
            assert len(set(o[0] for o in outcomes)) == 1, (
                "same reply produced different bubbles"
            )
            assert len(set(o[1] for o in outcomes)) == 1, (
                "same reply produced different card counts"
            )
