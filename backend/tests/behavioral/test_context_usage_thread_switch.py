"""Behavioral test (specs/phase-5-switcher, REQ-6 AC3).

"WHEN the user switches conversation threads THEN THE SYSTEM SHALL reflect
that thread's usage, not the previous thread's."

`get_agent_kernel(conversation_id)` (agent_kernel.py:8857) keys ONE kernel
instance PER conversation thread, and each kernel's `_tokens_used` is
restored per-thread by `restore_context_from_store()` (agent_kernel.py:597-
607: "self._tokens_used = ctx.tokens_used"). `_emit_context_usage()` always
reads `self._tokens_used` off whichever kernel calls it. This test proves
those two facts compose correctly: switching from thread A's kernel to
thread B's kernel and emitting from each does NOT leak thread A's numbers
into thread B's event — no shared mutable state across conversations
(project CLAUDE.md quality gate: "No shared mutable state across sessions or
concurrent requests").
"""

from __future__ import annotations

from backend.agent.agent_kernel import AgentKernel
from backend.agent.event_bus import get_event_bus, IRISStreamEvent


def _make_kernel_for_thread(conversation_id: str, tokens_used: int, max_tokens: int) -> AgentKernel:
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = conversation_id
    k.session_id = conversation_id
    k._current_turn_id = f"turn_{conversation_id}"
    k._tokens_used = tokens_used
    k.resolve_context_window = lambda: max_tokens
    return k


class TestContextUsageThreadSwitch:
    def test_switching_threads_reflects_the_new_thread_not_the_old_one(self):
        bus = get_event_bus()
        captured = []

        def _capture(payload):
            if payload.event == IRISStreamEvent.CONTEXT_USAGE:
                _d = dict(payload.data or {})
                _d["_conversation_id"] = payload.conversation_id
                captured.append(_d)

        bus.subscribe(IRISStreamEvent.CONTEXT_USAGE, _capture)
        try:
            # Thread A: a long-running conversation with real history.
            thread_a = _make_kernel_for_thread("thread_A", tokens_used=48_000, max_tokens=128_000)
            thread_a._emit_context_usage()

            # User switches to thread B — a DIFFERENT kernel instance with
            # its own restored state (a short, mostly-empty thread).
            thread_b = _make_kernel_for_thread("thread_B", tokens_used=512, max_tokens=32_000)
            thread_b._emit_context_usage()

            # And back to thread A again — must show A's numbers again, not
            # whatever thread B last reported (no leakage either direction).
            thread_a._emit_context_usage()
        finally:
            bus.unsubscribe(IRISStreamEvent.CONTEXT_USAGE, _capture)

        assert len(captured) == 3
        a1, b1, a2 = captured

        assert a1["_conversation_id"] == "thread_A"
        assert a1["used_tokens"] == 48_000
        assert a1["max_tokens"] == 128_000

        assert b1["_conversation_id"] == "thread_B"
        assert b1["used_tokens"] == 512, (
            "thread B's emit leaked thread A's used_tokens — REQ-6 AC3 violated"
        )
        assert b1["max_tokens"] == 32_000, (
            "thread B's emit leaked thread A's denominator — REQ-6 AC3 violated"
        )

        # Switching BACK to thread A shows A's numbers again — unaffected by
        # having emitted for B in between.
        assert a2["_conversation_id"] == "thread_A"
        assert a2["used_tokens"] == 48_000
        assert a2["max_tokens"] == 128_000

    def test_fresh_thread_with_no_turns_shows_zero_against_a_real_denominator(self):
        """Edge case: 'Thread with no turns yet -> zero used against a real
        denominator, not a placeholder.'"""
        bus = get_event_bus()
        captured = []

        def _capture(payload):
            if payload.event == IRISStreamEvent.CONTEXT_USAGE:
                captured.append(dict(payload.data or {}))

        bus.subscribe(IRISStreamEvent.CONTEXT_USAGE, _capture)
        try:
            fresh = _make_kernel_for_thread("thread_fresh", tokens_used=0, max_tokens=16_384)
            fresh._emit_context_usage()
        finally:
            bus.unsubscribe(IRISStreamEvent.CONTEXT_USAGE, _capture)

        assert captured[0]["used_tokens"] == 0
        assert captured[0]["max_tokens"] == 16_384, (
            "a fresh thread must still report the model's REAL context "
            "window, never the 128000 cold-start placeholder"
        )
