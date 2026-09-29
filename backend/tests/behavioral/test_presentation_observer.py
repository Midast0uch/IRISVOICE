"""Behavioral test: the presentation observer's degrade path (REQ-23 AC23.4).

When the engine is unavailable, the gate returns None and the caller takes
its legacy heuristic path.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import backend.agent.decision_engine as de_mod
from backend.agent.agent_kernel import AgentKernel


class TestEngineUnavailableReturnsNone:
    def test_engine_unavailable_returns_none(self, monkeypatch):
        """AC23.4: the engine unavailable → the gate returns None — the
        caller takes its legacy heuristic path. Never raises."""
        monkeypatch.setattr(de_mod, "_ENGINE", None)

        def boom():
            raise RuntimeError("engine chain broken")

        monkeypatch.setattr(de_mod, "get_decision_engine", boom)
        ks = SimpleNamespace(
            _last_render_emitted=False,
            _pacman_zone_for_turn=lambda: "reference",
            _launcher_mode="personal",
            _tool_bridge=None,
            session_id="s1",
        )
        out = AgentKernel._engine_gate_surface(ks, "a reply", turn_id="t1")
        assert out is None

    def test_engine_dead_returns_none(self, monkeypatch):
        """The engine answers None (dead) → the gate returns None."""
        class _DeadEngine:
            model_id = "dead"
            _cfg = SimpleNamespace(threshold_for=lambda c: 0.85)

            def decide(self, consumer_id, options, frame):
                return None

        monkeypatch.setattr(de_mod, "get_decision_engine",
                            lambda: _DeadEngine())
        ks = SimpleNamespace(
            _last_render_emitted=False,
            _pacman_zone_for_turn=lambda: "reference",
            _launcher_mode="personal",
            _tool_bridge=None,
            session_id="s1",
        )
        out = AgentKernel._engine_gate_surface(ks, "a reply", turn_id="t1")
        assert out is None
