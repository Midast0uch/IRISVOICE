"""Contract tests: CT-DEI-13 — the presentation observer seam (REQ-23, T33).

AC23.3  the gate writes NO steering field on any path.
AC23.5  the gate emits the SAME meta row shape on both the enforced and the
        shadow path, with `route` distinguishing them, so calibration joins.
AC23.6  the gate is gate-layer only — surface choice, never content.

AC23.1/AC23.2/AC23.4 are behavioural and pinned by
`tests/behavioral/test_decision_engine_gates.py` (the two RED tests T33 had to
make green without editing them) and `test_presentation_observer.py`.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

from backend.agent.agent_kernel import AgentKernel
from backend.agent.decision_engine import CandidateScore, DecisionScore


class _Engine:
    def __init__(self, chosen="prism_card", confidence=0.9, threshold=0.40):
        self._chosen, self._conf = chosen, confidence
        self.model_id = "gate-stub"
        self._cfg = SimpleNamespace(threshold_for=lambda consumer: threshold)

    def decide(self, consumer_id, options, frame):
        return DecisionScore(
            consumer_id=consumer_id, chosen=self._chosen, confidence=self._conf,
            distribution=tuple(
                CandidateScore(o, -0.1, 0.9 if o == self._chosen else 0.03)
                for o in options
            ),
            engine_latency_ms=2,
        )


class _Bridge:
    def __init__(self):
        self.rows: list = []

    def record_decision(self, meta, kind, error=None, session_id="unknown"):
        self.rows.append((dict(meta), kind))


def _kernel(engine, monkeypatch, *, enforced=False, card_emitted=False):
    k = AgentKernel.__new__(AgentKernel)
    k._last_render_emitted = card_emitted
    k._tool_bridge = _Bridge()
    k.session_id = "s-gate"
    monkeypatch.setattr(k, "_pacman_zone_for_turn", lambda: "chat", raising=False)
    monkeypatch.setattr(
        "backend.agent.decision_engine.get_decision_engine", lambda: engine)
    monkeypatch.setattr(
        "backend.agent.decision_engine.enforced_consumers",
        lambda: frozenset({"presentation"}) if enforced else frozenset(),
    )
    return k


class TestNoSteeringFieldWritten:
    def test_no_steering_field_written(self, monkeypatch):
        """AC23.3: no path writes `_last_surface_choice` or any steering field."""
        for enforced in (False, True):
            k = _kernel(_Engine(), monkeypatch, enforced=enforced)
            k._engine_gate_surface("a short reply")
            assert not hasattr(k, "_last_surface_choice"), (
                "the gate wrote a steering field — AC23.3 forbids it "
                f"(enforced={enforced})"
            )
        # ...and the gate's own source contains no assignment to it.
        src = inspect.getsource(AgentKernel._engine_gate_surface)
        assert "_last_surface_choice =" not in src, (
            "a steering-field assignment reappeared in the gate"
        )

    def test_engine_unavailable_returns_none_with_no_row_no_write(
        self, monkeypatch,
    ):
        """AC23.4 edge: card rendered AND engine unavailable → None, no row,
        no steering write."""
        k = _kernel(_Engine(), monkeypatch, card_emitted=True)

        def _dead():
            raise RuntimeError("engine dead")

        monkeypatch.setattr(
            "backend.agent.decision_engine.get_decision_engine", _dead)

        assert k._engine_gate_surface("hi") is None
        assert k._tool_bridge.rows == []
        assert not hasattr(k, "_last_surface_choice")


class TestMetaRowShapeBothPaths:
    def test_meta_row_shape_both_paths(self, monkeypatch):
        """AC23.5: identical key set on both paths; `route` distinguishes."""
        shapes = {}
        for enforced, expected_route in ((False, "shadow"), (True, "engine")):
            k = _kernel(_Engine(confidence=0.9), monkeypatch, enforced=enforced)
            k._engine_gate_surface("a short reply")

            assert k._tool_bridge.rows, (
                f"no ledger row on the {expected_route} path"
            )
            meta, kind = k._tool_bridge.rows[0]
            assert kind == "surface"
            assert meta["consumer_id"] == "presentation"
            assert meta["route"] == expected_route
            shapes[expected_route] = set(meta.keys())

        assert shapes["shadow"] == shapes["engine"], (
            "the enforced and shadow paths emit different row shapes — "
            "calibration cannot join them uniformly (AC23.5)"
        )

    def test_card_turn_frame_is_truthful(self, monkeypatch):
        """AC23.2: a card turn still yields a verdict, and the frame admits the
        card exists."""
        engine = _Engine()
        k = _kernel(engine, monkeypatch, card_emitted=True)
        seen: dict = {}
        inner = engine.decide

        def _capture(consumer_id, options, frame):
            seen.update(frame)
            return inner(consumer_id, options, frame)

        engine.decide = _capture

        assert k._engine_gate_surface("a short reply") is not None
        assert seen["card_already_rendered"] is True, (
            "the frame hardcoded card_already_rendered=False on a card turn"
        )


class TestGateLayerOnly:
    def test_gate_layer_only_never_content(self, monkeypatch):
        """AC23.6: the frame carries gate-layer signals only — the reply text
        must never leak into it."""
        engine = _Engine()
        k = _kernel(engine, monkeypatch)
        seen: dict = {}
        inner = engine.decide

        def _capture(consumer_id, options, frame):
            seen.update(frame)
            return inner(consumer_id, options, frame)

        engine.decide = _capture
        k._engine_gate_surface("SECRET-REPLY-BODY")

        assert seen, "the engine was never consulted"
        assert all("SECRET-REPLY-BODY" not in str(v) for v in seen.values()), (
            "the reply text leaked into the engine frame — the gate must be "
            "gate-layer only (AC23.6)"
        )
        assert "content" not in seen
        # gate-layer signals only
        assert set(seen) <= {
            "content_chars", "has_structure", "card_already_rendered",
            "zone", "mode",
        }, seen.keys()
