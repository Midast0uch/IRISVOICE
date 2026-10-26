"""The ContextPill shows how FULL the window is, not what the thread has spent (owner, 2026-10-26).

Before: used_tokens was self._tokens_used, the running sum of every call of the thread (never reset, ~20k per DER
turn), so a thread went red after a few turns with nothing near the limit. Now used_tokens is the largest single
call (prompt + answer, real usage) of the thread's latest turn; the spend still travels as spent_tokens.
"""
from __future__ import annotations

from backend.agent.agent_kernel import AgentKernel
from backend.agent.conversation_context_store import ConversationContext
from backend.agent.event_bus import IRISStreamEvent, get_event_bus


def _kernel():
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id, k.session_id, k._current_turn_id = "conv-fill", "sess", None
    k.resolve_context_window = lambda: 260_000
    return k


def _emit(k):
    got = []

    def _cap(p):
        if p.event == IRISStreamEvent.CONTEXT_USAGE:
            got.append(dict(p.data or {}))

    bus = get_event_bus()
    bus.subscribe(IRISStreamEvent.CONTEXT_USAGE, _cap)
    try:
        k._emit_context_usage()
    finally:
        bus.unsubscribe(IRISStreamEvent.CONTEXT_USAGE, _cap)
    return got[0]


def _call(k, total):
    k._accrue_tokens("x", {"prompt_tokens": total - 100, "completion_tokens": 100, "total_tokens": total})


def test_the_pill_shows_the_largest_call_of_the_latest_turn_not_the_running_spend():
    k = _kernel()
    k._current_turn_id = "t1"
    for total in (2_000, 23_000, 5_000):          # a DER turn: plan, a big synthesis, a small narration
        _call(k, total)
    d = _emit(k)
    assert d["used_tokens"] == 23_000 and d["spent_tokens"] == 30_000 and d["max_tokens"] == 260_000

    k._current_turn_id = "t2"                       # the next turn is smaller: the window is LESS full now
    for total in (1_500, 4_000):
        _call(k, total)
    d = _emit(k)
    assert d["used_tokens"] == 4_000                # not 23_000, and not the 35_500 spent
    assert d["spent_tokens"] == 35_500


def test_ten_agent_turns_never_add_up_past_the_window():
    """The old pill crossed 85 % (red) of 260k after ~10 turns of ~23k each."""
    k = _kernel()
    for i in range(12):
        k._current_turn_id = f"t{i}"
        for total in (2_000, 23_000, 5_000):
            _call(k, total)
    d = _emit(k)
    assert d["used_tokens"] == 23_000 and d["used_tokens"] / d["max_tokens"] < 0.6
    assert d["spent_tokens"] == 12 * 30_000


def test_the_fill_is_saved_and_restored_per_thread():
    ctx = ConversationContext.from_dict({"conversation_id": "c", "messages": [], "tokens_used": 99_000,
                                         "context_fill": 23_000})
    assert ctx.context_fill == 23_000
    old = ConversationContext.from_dict({"conversation_id": "c", "messages": [], "tokens_used": 99_000})
    assert old.context_fill == 0                    # a row saved before the field existed still loads
