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
from types import SimpleNamespace

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
        only tool_choice is enforced by default (IRIS_DECISION_ENFORCE).

        SUPERSEDED COUNT (2026-09-26, session 357): CT-10a originally pinned a
        THREE-consumer set. specs/tool-decision-engine-improvements REQ-11/13/
        14/15/17/29 mandate the additional consumers, and the two CT-DE-7
        enumerations were already grown STALE-BY-SPEC for the same reason. What
        CT-10a actually PROTECTS is asserted below and is UNCHANGED —
        `presentation` is still preserved, and it is still an OBSERVER.
        """
        assert set(de.CONSUMERS) == {
            "tool_choice", "presentation", "narration", "recovery_strategy",
            "review_verdict", "sufficient", "done", "on_track",
            "mode", "web_intent", "retry_same",
            "has_gaps", "use_thinking", "escalate_incomplete", "needs_action",
            # Session 364 (owner request): the DEPTH consumer, scored at the
            # run-grade chokepoint against the task's success criteria.
            "depth_met",
        }, (
            "the consumer set changed — cross-spec lock with "
            "specs/tool-decision-engine REQ-11/13/14/15/17/29"
        )
        # The properties CT-10a exists for, asserted directly so a count
        # change can never silently delete the observer.
        assert "presentation" in de.CONSUMERS, (
            "CT-10a: the presentation consumer must stay PRESERVED (not "
            "deleted) — it is the calibration observer"
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


# ---------------------------------------------------------------------------
# CT-DEI-13 — presentation observer shape (REQ-23, tool-decision-engine-improvements)
# ---------------------------------------------------------------------------


class _RowEngine:
    """Engine stand-in that answers fixed and records nothing itself."""

    def __init__(self, chosen="prism_card", confidence=0.97):
        self.model_id = "row-stub"
        self._chosen = chosen
        self._conf = confidence
        self._cfg = SimpleNamespace(threshold_for=lambda c: 0.85)

    def decide(self, consumer_id, options, frame):
        return SimpleNamespace(
            chosen=self._chosen,
            confidence=self._conf,
            engine_latency_ms=2,
            distribution=None,
        )


class TestNoSteeringFieldWritten:
    def test_no_steering_field_written(self, monkeypatch):
        """AC23.3 / CT-DEI-13: the gate writes NO steering side-channel —
        `_last_surface_choice` is read nowhere and the writes are removed."""
        engine = _RowEngine()
        monkeypatch.setattr(de, "get_decision_engine", lambda: engine)
        k, bus = _kernel(monkeypatch, zone="reference")
        AgentKernel._engine_gate_surface(k, "a reply", turn_id="t1")
        assert not hasattr(k, "_last_surface_choice"), (
            "the dead steering field came back — the gate must not write it"
        )


class TestMetaRowShapeBothPaths:
    def test_meta_row_shape_both_paths(self, monkeypatch):
        """AC23.5 / CT-DEI-13: the observer row carries the same shape on
        BOTH paths (engine and shadow) so calibration joins work uniformly."""
        rows = []

        def rec(meta, kind, session_id="unknown"):
            rows.append((meta, kind))

        # Shadow path.
        engine = _RowEngine()
        monkeypatch.setattr(de, "get_decision_engine", lambda: engine)
        k = SimpleNamespace(
            _last_render_emitted=False,
            _pacman_zone_for_turn=lambda: "reference",
            _launcher_mode="personal",
            _tool_bridge=SimpleNamespace(record_decision=rec),
            session_id="s1",
        )
        AgentKernel._engine_gate_surface(k, "a reply", turn_id="t1")
        assert rows, "shadow path recorded no row"
        shadow_meta = rows[0][0]
        expected = {
            "engine", "consumer_id", "chosen", "confidence", "candidates",
            "threshold", "args_valid", "retried", "engine_latency_ms",
            "route", "escalated",
        }
        assert expected <= set(shadow_meta), (
            f"shadow row shape drifted: {expected - set(shadow_meta)}"
        )
        assert shadow_meta["route"] == "shadow"
        # Engine path (enforced + confident).
        rows.clear()
        monkeypatch.setenv("IRIS_DECISION_ENFORCE", "tool_choice,presentation")
        k2 = SimpleNamespace(
            _last_render_emitted=False,
            _pacman_zone_for_turn=lambda: "reference",
            _launcher_mode="personal",
            _tool_bridge=SimpleNamespace(record_decision=rec),
            session_id="s1",
        )
        AgentKernel._engine_gate_surface(k2, "a reply", turn_id="t2")
        assert rows, "engine path recorded no row"
        engine_meta = rows[0][0]
        assert expected <= set(engine_meta), (
            f"engine row shape drifted: {expected - set(engine_meta)}"
        )
        assert engine_meta["route"] == "engine"


class TestGateLayerOnlyNeverContent:
    def test_gate_layer_only_never_content(self, monkeypatch):
        """AC23.6 / CT-DEI-13: the gate is gate-LAYER only — it returns a
        surface choice, never content, and never emits a content event."""
        engine = _RowEngine()
        monkeypatch.setattr(de, "get_decision_engine", lambda: engine)
        k, bus = _kernel(monkeypatch, zone="reference")
        out = AgentKernel._engine_gate_surface(k, "a reply body", turn_id="t1")
        assert out in ("card", "plain", None), (
            f"the gate returned a non-surface value: {out!r}"
        )
        assert bus.events == [], "the gate emitted an event"
        # The gate never shortens content: the reply text is untouched.
        assert k._last_spoken_text == ""
