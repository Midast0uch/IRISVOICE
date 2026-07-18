"""Unit tests: REQ-7 physics-event narration trigger (pure logic).

The agent speaks ONLY on a physics event — a |u| transition (oscillating ->
converged) or a structural event (split into Sub-Loops, Sub-Loop collapse).
Ordinary steps return None -> the agent stays SILENT (no per-step heartbeat).
This is the agent-driven, latency-cheap post-step hook.

Spec: specs/der-loop-integrity-display/requirements.md REQ-7.
"""

from __future__ import annotations

from backend.agent.der_constants import (
    U_CONVERGED,
    U_SPLIT,
    detect_physics_narration,
)


class TestPhysicsNarrationTrigger:
    def test_silent_on_ordinary_step(self):
        # Same |u| band, no children, not a subloop -> silence.
        assert detect_physics_narration(0.6, 0.62, False, False) is None
        assert detect_physics_narration(0.2, 0.25, False, False) is None

    def test_silent_on_first_step(self):
        # prev_u_mag is None on the first step -> no transition line.
        assert detect_physics_narration(None, 0.9, False, False) is None

    def test_split_speaks(self):
        line = detect_physics_narration(0.6, 0.6, 3, False)
        assert line is not None
        assert "sub-task" in line
        assert "3" in line

    def test_split_takes_precedence_over_transition(self):
        # Even if |u| also transitions, a split wins.
        line = detect_physics_narration(0.6, 0.95, 2, False)
        assert "sub-task" in line

    def test_subloop_collapse_speaks(self):
        line = detect_physics_narration(0.6, 0.6, 0, True)
        assert line is not None
        assert "folding back" in line

    def test_oscillating_to_converged_speaks(self):
        # prev oscillating (>U_SPLIT), now converged (>=U_CONVERGED).
        line = detect_physics_narration(U_SPLIT + 0.1, U_CONVERGED, False, False)
        assert line is not None
        assert "answer" in line

    def test_converged_to_oscillating_speaks(self):
        line = detect_physics_narration(U_CONVERGED, U_SPLIT + 0.1, False, False)
        assert line is not None
        assert "search" in line

    def test_no_transition_when_staying_oscillating(self):
        # Both sides oscillating, no structural event -> silence.
        assert detect_physics_narration(0.6, 0.7, False, False) is None

    def test_no_transition_when_staying_converged(self):
        assert detect_physics_narration(0.95, 0.9, False, False) is None
