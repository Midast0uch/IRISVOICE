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

    # Owner 2026-10-02: the split lines say what the part is about, in plain
    # words ("Sub-task done; folding back into the main thread" was jargon).

    def test_split_speaks(self):
        line = detect_physics_narration(0.6, 0.6, 3, False)
        assert line is not None
        assert "3 parts" in line

    def test_split_takes_precedence_over_transition(self):
        # Even if |u| also transitions, a split wins.
        line = detect_physics_narration(0.6, 0.95, 2, False)
        assert "2 parts" in line

    def test_subloop_collapse_speaks(self):
        line = detect_physics_narration(0.6, 0.6, 0, True)
        assert line is not None
        assert "done" in line

    def test_split_names_the_step(self):
        line = detect_physics_narration(
            0.6, 0.6, 2, False,
            step_description="Read the textutils.py file to see its current content.")
        assert "read the textutils.py file to see its current content" in line

    def test_part_done_names_the_parent_step_not_the_machine_anchor(self):
        line = detect_physics_narration(
            0.6, 0.6, 0, True,
            step_description="RESOLVE: result did not satisfy expected output: x (sub 1)",
            parent_description="Fix the import error in shapes/__init__.py.")
        assert "fix the import error in shapes/__init__.py" in line
        assert "RESOLVE" not in line

    def test_machine_text_is_never_spoken_and_no_jargon_remains(self):
        for line in (
            detect_physics_narration(0.6, 0.6, 2, False, step_description="RESOLVE: blocker x"),
            detect_physics_narration(0.6, 0.6, 0, True, parent_description="Replan required: stuck"),
        ):
            assert "RESOLVE" not in line and "Replan" not in line
            assert "sub-task" not in line and "folding back" not in line
            assert "main thread" not in line

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
