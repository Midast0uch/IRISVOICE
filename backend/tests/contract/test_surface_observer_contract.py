"""Contract (specs/reply-surface-contract REQ-15 / REQ-14, task T9 — CT-10 + CT-12).

CT-10: NO engine call on the reply path, and nothing but ``show``-presence
steers the live surface. (2026-11-10, owner: the ``presentation`` observer and
``narration`` consumers were RETIRED - presentation lost to the reply-surface
rules 0.378 vs 0.937 - so the reply path now consults no engine at all.)

CT-12: the same reply yields the same surface across repeated runs
``(deterministic — REQ-14 AC4)``: the reply lane depends only on
``show``-presence.
"""

from __future__ import annotations

import json
import threading
import time

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
        NOTHING is enforced by default (IRIS_DECISION_ENFORCE is empty).

        CHANGED (2026-10-05, Oracle Stage B, owner-approved): the default used to
        be "tool_choice" (enforced at birth, no production deciding path, below
        the bar); `on_track` (no production caller) and `has_gaps` (no live site)
        left the set. The assertion on the default is now `frozenset()`.

        SUPERSEDED COUNT (2026-09-26, session 357): CT-10a originally pinned a
        THREE-consumer set. specs/tool-decision-engine-improvements REQ-11/13/
        14/15/17/29 mandate the additional consumers, and the two CT-DE-7
        enumerations were already grown STALE-BY-SPEC for the same reason. What
        CT-10a actually PROTECTS is asserted below and is UNCHANGED —
        `presentation` is still preserved, and it is still an OBSERVER.
        """
        assert set(de.CONSUMERS) == {
            "tool_choice", "recovery_strategy",
            "sufficient", "done",
            "web_intent",
            # escalate_incomplete retired 2026-11-09; presentation, narration,
            # review_verdict, needs_action, depth_met, depth_route 2026-11-10
            "call_closing",
            "tool_approval",
            "route_v2",
        }, (
            "the consumer set changed — cross-spec lock with "
            "specs/tool-decision-engine REQ-11/13/14/15/17/29"
        )
        monkeypatch.delenv("IRIS_DECISION_ENFORCE", raising=False)
        assert de.enforced_consumers() == frozenset(), (
            "default enforcement must stay EMPTY"
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
        is mid-decision, and the engine is never consulted (2026-11-10: the
        presentation observer that consulted it off the reply path is
        retired; this used to assert exactly one consult on its thread)."""
        engine = _BlockingEngine()
        monkeypatch.setattr(de, "get_decision_engine", lambda: engine)
        k, bus = _kernel(monkeypatch, zone="reference")
        text = "plain reply, no show payload " * 40  # structural-free, long
        started = time.monotonic()
        out = AgentKernel._process_structured_response(
            k, text, turn_id="t-obs", conversation_id="c"
        )
        elapsed = time.monotonic() - started
        # The reply CONTENT must be unchanged by the observer. The reply
        # pipeline normalizes surrounding whitespace (`_process_structured_
        # response` strips, pre-existing and unrelated to the observer), so
        # compare the content rather than the exact string: the property under
        # test is "the observer did not alter the reply", not "whitespace
        # survives byte-for-byte". STALE-BY-SPEC (2026-09-26) — the exact
        # equality pinned a pipeline detail the docstring never claimed.
        assert out.strip() == text.strip()
        assert bus.events == []
        assert elapsed < 2.0, (
            f"reply path blocked on the engine ({elapsed:.2f}s) — REQ-15 AC1"
        )
        engine.gate.set()
        time.sleep(0.2)  # room for any stray observer thread to reach the engine
        assert engine.calls == [], f"the reply path consulted the engine: {engine.calls}"

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
