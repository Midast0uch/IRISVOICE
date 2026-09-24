"""Contract (reply-surface-contract REQ-18, session 349, tasks T31 + T32).

T31 — prompt battery: the classification contract for unified routing. The
gate's `requires_der_kernel` answer IS the triviality classifier (owner
decision 2026-09-22: rules first, engine may shadow-vote later). This battery
drives the REAL `_needs_planning` path over the verified prompt matrix from
tests/behavioral/test_behavioral_intent_routing.py (which the 69-case gate
proof already pins) and asserts the route-level contract:

    chitchat / questions / follow-ups WITHOUT tool need  -> trivial (direct)
    action / web / compound / reminder-style prompts     -> DER

T32 — no task cards on trivial turns (owner rule: "task cards not triggered
by every prompt"). A turn the gate classifies as trivial runs the direct
executor and MUST NOT emit task:start (or any task lifecycle event). Pinned
end-to-end through the real `process_text_message` direct branch.
"""

from __future__ import annotations

from backend.agent.agent_kernel import AgentKernel
from backend.agent.event_bus import IRISStreamEvent, get_event_bus

from backend.tests.behavioral.test_behavioral_intent_routing import (
    TASK_CTX,
    _ACTION,
    _CHITCHAT,
    _COMPOUND,
    _FOLLOWUP,
    _QUESTION,
    _WEB,
)


def _make_kernel():
    k = AgentKernel.__new__(AgentKernel)
    k._tool_mode = "auto"
    k._memory_interface = None
    return k


class TestTrivialityClassificationBattery:
    """T31: route intent matches the trivial/DER split on every prompt class."""

    def test_chitchat_is_trivial(self):
        k = _make_kernel()
        for text in _CHITCHAT:
            assert k._needs_planning(text, None) is False, (
                f"chitchat must never route to DER/task mode: {text!r}"
            )

    def test_questions_are_trivial(self):
        k = _make_kernel()
        for text in _QUESTION:
            assert k._needs_planning(text, None) is False, (
                f"plain questions must never route to DER/task mode: {text!r}"
            )

    def test_web_prompts_route_to_der(self):
        k = _make_kernel()
        for text in _WEB:
            assert k._needs_planning(text, None) is True, (
                f"web work must stay on the DER path: {text!r}"
            )

    def test_action_prompts_route_to_der(self):
        k = _make_kernel()
        for text in _ACTION:
            assert k._needs_planning(text, None) is True, (
                f"tool-backed work must route to DER: {text!r}"
            )

    def test_followup_with_tool_continuity_routes_to_der(self):
        k = _make_kernel()
        for text in _FOLLOWUP:
            assert k._needs_planning(text, TASK_CTX) is True, (
                f"tool-context follow-up must route to DER: {text!r}"
            )

    def test_compound_prompts_route_to_der(self):
        k = _make_kernel()
        for text in _COMPOUND:
            assert k._needs_planning(text, None) is True, (
                f"compound prompts must route to DER: {text!r}"
            )


class _FakeConversationMemory:
    def __init__(self):
        self.messages = []

    def add_message(self, role, text):
        self.messages.append({"role": role, "text": text})

    def get_context(self):
        return list(self.messages)


def _make_direct_kernel():
    """Real process_text_message up to the direct executor; everything
    downstream (model, shaping, memory jobs) canned, like the
    context_usage_on_direct_reply fixture."""
    k = AgentKernel.__new__(AgentKernel)
    k.session_id = "sess_t32"
    k.conversation_id = "conv_t32"
    k._pending_thinking = ""
    k._initialization_error = None
    # Availability guard (`agent_kernel.py:6953`) checks `_model_router` and
    # `_conversation_memory` only for truthiness — a non-None placeholder is
    # enough; generation itself is stubbed below.
    k._model_router = object()
    k._conversation_memory = _FakeConversationMemory()
    k._mcm_orch = None
    k._memory_interface = None
    k._tokens_used = 0
    k.resolve_context_window = lambda: 8_192
    k._needs_planning = lambda text, context: False          # trivial turn
    k._respond_direct = lambda text, context, chunk_callback=None, reasoning_callback=None: (
        "Hello! Plain answer, no tools."
    )
    k._process_structured_response = lambda response, turn_id=None, conversation_id=None: response
    k._maybe_escalate_web_format = lambda task_id, conv_id, response_text="": None
    k.clear_turn_trust_flag = lambda: None
    return k


class TestRouteShadowLogging:
    """T30 (REQ-18 AC1): every turn leaves a route-shadow row — this is the
    parity evidence the T33 flip reads."""

    def test_a_turn_writes_a_shadow_row(self):
        import json
        from pathlib import Path
        import backend.agent.agent_kernel as ak

        real_log = (
            Path(ak.__file__).resolve().parents[2] / "data" / "route_shadow.jsonl"
        )
        before = real_log.read_text(encoding="utf-8").count("\n") if real_log.exists() else 0

        k = _make_direct_kernel()
        # The stub sets no turn handler — the production call always sets
        # `_current_turn_id` before the seam runs; we need one so the shadow
        # line is not produced with "unknown".
        k._current_turn_id = "test-t30"
        k.process_text_message("hello there", session_id="sess_t30")
        # Writer is synchronous via open()+write() — give the kernel half a
        # beat so the row is on disk before we count.
        import time
        time.sleep(0.2)

        after = real_log.read_text(encoding="utf-8").count("\n") if real_log.exists() else 0
        assert after == before + 1, "a turn must append exactly one shadow row"

        last = json.loads(
            real_log.read_text(encoding="utf-8").strip().split("\n")[-1]
        )
        assert last["turn_id"] != "unknown"
        assert last["route_taken"] == "direct"      # stub forces planning off
        assert last["would_be_trivial"] is True
        assert last["chars"] == len("hello there")


class TestTrivialTurnNeverMintsATaskCard:
    """T32 (REQ-18 AC3): owner rule — task cards exist for real multi-tool
    tasks only; a trivial prompt must never surface one."""

    _TASK_EVENTS = (
        IRISStreamEvent.TASK_START, IRISStreamEvent.TASK_PROGRESS,
        IRISStreamEvent.TASK_MILESTONE, IRISStreamEvent.TASK_DONE,
        IRISStreamEvent.TASK_FAIL,
    )

    def test_trivial_turn_emits_no_task_lifecycle_events(self):
        bus = get_event_bus()
        captured = []

        for ev in self._TASK_EVENTS:
            bus.subscribe(ev, lambda payload, _c=captured: _c.append(payload))

        try:
            k = _make_direct_kernel()
            response = k.process_text_message("what time is it?", session_id="sess_t32")
        finally:
            for ev in self._TASK_EVENTS:
                try:
                    bus.unsubscribe(ev, lambda payload: None)
                except Exception:
                    pass

        assert response == "Hello! Plain answer, no tools."
        assert captured == [], (
            f"a trivial turn must mint no task card; got: {[getattr(p, 'event', p) for p in captured]}"
        )
