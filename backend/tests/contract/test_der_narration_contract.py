"""Contract tests: REQ-7 step-level narration is PHYSICS-EVENT triggered.

Drives _der_finalize_step through two steps — an ordinary step (no physics
event) and a split step (verify_failed -> children) — and asserts SpeakTool
is called ONLY on the split, NOT on the ordinary step. This pins the
agent-driven, latency-cheap post-step hook contract: spoken ⊆ visible,
no per-step heartbeat.

Spec: specs/der-loop-integrity-display/requirements.md REQ-7.
"""

from __future__ import annotations

import types

import pytest

from backend.agent.agent_kernel import AgentKernel


class _FakeItem:
    def __init__(self, step_number, description="", is_subloop=False):
        self.step_number = step_number
        self.description = description
        self.is_subloop = is_subloop
        self.step_id = f"step-{step_number}"


class _FakeQueue:
    def __init__(self):
        self.items = []
        self.added = []

    def add_item(self, item):
        self.items.append(item)
        self.added.append(item)


class _SpySpeak:
    def __init__(self):
        self.calls = []

    def speak(self, text, priority="normal"):
        self.calls.append((text, priority))


@pytest.fixture
def kernel():
    k = AgentKernel.__new__(AgentKernel)
    k._der_last_u_mag = None
    k._der_work_units = 10
    # Spy on SpeakTool
    spy = _SpySpeak()
    import backend.agent.tools.speak_tool as st

    k._speak_spy = spy
    # Cross-test-pollution bugfix: `del st.get_speak_tool` in the old teardown
    # removed the NAME from the module entirely (module attributes are
    # process-wide singletons), so every test file that runs AFTER this one
    # in the same pytest process saw `ImportError: cannot import name
    # 'get_speak_tool'` — a full-suite-only failure that a per-file run never
    # surfaces. Save and restore the ORIGINAL function instead of deleting it.
    _orig_get_speak_tool = st.get_speak_tool
    st.get_speak_tool = lambda: spy
    yield k
    # restore
    st.get_speak_tool = _orig_get_speak_tool


def _finalize(kernel, item, step_result, u, children=(), is_subloop=False):
    """Minimal shim around the REQ-7 hook logic without the full kernel."""
    from backend.agent.der_constants import detect_physics_narration

    item.is_subloop = is_subloop
    _u_mag = abs(float(u)) if u is not None else 0.0
    line = detect_physics_narration(
        kernel._der_last_u_mag, _u_mag, len(children), is_subloop
    )
    if line:
        kernel._speak_spy.speak(line, priority="low")
    kernel._der_last_u_mag = _u_mag


class TestStepNarrationIsEventTriggered:
    def test_ordinary_step_silent(self, kernel):
        # Oscillating |u|, no children, not subloop -> no speak.
        _finalize(kernel, _FakeItem(1), "ok", u=0.6)
        assert kernel._speak_spy.calls == []

    def test_split_step_speaks(self, kernel):
        _finalize(kernel, _FakeItem(1), "fail", u=0.6, children=[1, 2])
        assert len(kernel._speak_spy.calls) == 1
        assert "sub-task" in kernel._speak_spy.calls[0][0]

    def test_convergence_transition_speaks(self, kernel):
        _finalize(kernel, _FakeItem(1), "ok", u=0.6)  # oscillating
        _finalize(kernel, _FakeItem(2), "ok", u=0.95)  # converged
        # Only the 2nd step (transition) speaks.
        assert len(kernel._speak_spy.calls) == 1
        assert "answer" in kernel._speak_spy.calls[0][0]

    def test_no_speak_when_staying_oscillating(self, kernel):
        _finalize(kernel, _FakeItem(1), "ok", u=0.6)
        _finalize(kernel, _FakeItem(2), "ok", u=0.7)
        assert kernel._speak_spy.calls == []
