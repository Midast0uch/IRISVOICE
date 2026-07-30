"""Behavioral test (specs/phase-5-switcher, REQ-6 AC1) — 'Fails today' per
design.md's original framing, describing the gap BEFORE the Wave 9 fix
(`self._emit_context_usage()` calls in `process_text_message`, agent_kernel.py
~:4433 direct / ~:6160 DER) landed. Recorded here as a standing behavioral
guard so the gap cannot silently reopen — this is exactly the kind of
regression a green unit suite would miss (a real reply completing with a
stale pill, no error, no failing test) because the frontend suite only
started running in Phase 2 (design.md).

Drives the REAL `AgentKernel.process_text_message` direct (non-DER) path —
not a re-implementation of it — with the model call, planning check, and
downstream response-shaping stubbed to canned values (the LLM and its
scaffolding are not what REQ-6 is about), and asserts `context:usage` fires
on the real EventBus with the real `resolve_context_window()` denominator.

NOT collected under a `test_` module top-level import of `agent_kernel`
that would spin up the full backend (mirrors `test_context_usage_emit.py`'s
own note) — run directly if invoked as a script; also perfectly safe to
collect under pytest since `AgentKernel.__new__` skips `__init__` entirely.
"""

from __future__ import annotations

from backend.agent.agent_kernel import AgentKernel
from backend.agent.event_bus import get_event_bus, IRISStreamEvent


class _FakeConversationMemory:
    def __init__(self):
        self.messages = []

    def add_message(self, role, text):
        self.messages.append({"role": role, "text": text})

    def get_context(self):
        return list(self.messages)


def _make_direct_path_kernel(tokens_used: int, max_tokens: int) -> AgentKernel:
    """A minimal-but-real kernel wired ONLY enough to exercise the direct
    (non-DER) branch of `process_text_message` — everything downstream of
    "which branch" (the model call, response shaping, pacman fragmentation)
    is stubbed to a canned value so this test is about the EMIT, not the LLM.
    """
    k = AgentKernel.__new__(AgentKernel)
    k.session_id = "sess_direct_reply"
    k.conversation_id = "conv_direct_reply"
    k._pending_thinking = ""
    k._initialization_error = None
    k._model_router = object()  # just needs to be truthy
    k._conversation_memory = _FakeConversationMemory()
    k._mcm_orch = None
    k._memory_interface = None
    k._tokens_used = tokens_used
    k.resolve_context_window = lambda: max_tokens

    # Route straight to the direct path (this is what REQ-6 is testing —
    # NOT the planning heuristic itself, which has its own tests).
    k._needs_planning = lambda text, context: False
    k._respond_direct = lambda text, context, chunk_callback=None, reasoning_callback=None: (
        "Hello! This is a direct, non-DER reply."
    )
    # Response-shaping is out of scope for REQ-6 — identity passthrough.
    k._process_structured_response = lambda response, turn_id=None, conversation_id=None: response
    k._maybe_escalate_web_format = lambda task_id, conv_id: None
    k.clear_turn_trust_flag = lambda: None
    return k


class TestContextUsageOnDirectReply:
    def test_direct_reply_emits_context_usage_with_real_denominator(self):
        bus = get_event_bus()
        captured = []

        def _capture(payload):
            if payload.event == IRISStreamEvent.CONTEXT_USAGE:
                captured.append(dict(payload.data or {}))

        bus.subscribe(IRISStreamEvent.CONTEXT_USAGE, _capture)
        try:
            k = _make_direct_path_kernel(tokens_used=4_200, max_tokens=32_000)
            response = k.process_text_message("hi there", session_id="sess_direct_reply")
        finally:
            bus.unsubscribe(IRISStreamEvent.CONTEXT_USAGE, _capture)

        assert response == "Hello! This is a direct, non-DER reply."
        assert len(captured) == 1, (
            f"expected exactly one context:usage emit from the direct reply "
            f"path (REQ-6 AC1), got {len(captured)}: {captured}"
        )
        assert captured[0]["max_tokens"] == 32_000, (
            "direct-path denominator must be resolve_context_window(), never "
            "a hardcoded placeholder (REQ-6 AC2)"
        )
        assert captured[0]["used_tokens"] == 4_200

    def test_streaming_direct_reply_emits_once_at_completion_not_per_chunk(self):
        """Edge case: 'Streaming reply -> emit at completion, not per chunk.'"""
        bus = get_event_bus()
        captured = []

        def _capture(payload):
            if payload.event == IRISStreamEvent.CONTEXT_USAGE:
                captured.append(dict(payload.data or {}))

        bus.subscribe(IRISStreamEvent.CONTEXT_USAGE, _capture)
        try:
            k = _make_direct_path_kernel(tokens_used=100, max_tokens=8_192)

            def _streaming_respond_direct(text, context, chunk_callback=None, reasoning_callback=None):
                # Simulate a real streaming provider invoking chunk_callback
                # several times before the method returns.
                for chunk in ("Hel", "lo ", "wor", "ld"):
                    if chunk_callback:
                        chunk_callback(chunk)
                return "Hello world"

            k._respond_direct = _streaming_respond_direct
            k.process_text_message("hi", session_id="sess_direct_reply")
        finally:
            bus.unsubscribe(IRISStreamEvent.CONTEXT_USAGE, _capture)

        assert len(captured) == 1, (
            f"a streaming direct reply must emit context:usage ONCE at "
            f"completion, not once per chunk — got {len(captured)} emits"
        )
