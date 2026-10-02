"""Contract: a node's working history survives the router's window cap.

Live 2026-10-02 (API tool models, window unknown -> 8192): a node asks for
max_tokens=8192, the old cap reserved 8192 + 256 for the answer, leaving a
256-token prompt budget. Every API node call went out as system + last
message only ("prompt over the window: window=8192 budget=256", up to 14
messages dropped): the node never saw the file it had just read, repeated its
calls, and the Brain reported "read_file returned no content".
"""
from __future__ import annotations

from backend.agent.inference.router import InferenceRouter


def _node_history(rounds: int, chars: int) -> list:
    msgs = [{"role": "system", "content": "You do coding work with tools."},
            {"role": "user", "content": "Add slugify(text) to textutils.py."}]
    for i in range(rounds):
        msgs.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": f"c{i}", "type": "function",
             "function": {"name": "read_file", "arguments": '{"path": "textutils.py"}'}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "name": "read_file",
                     "content": "x" * chars})
    return msgs


def test_a_node_history_that_fits_the_window_is_sent_whole():
    # ~3.4k tokens of history on an 8192 window with the node's max_tokens=8192
    msgs = _node_history(rounds=6, chars=2000)
    kept = InferenceRouter._cap_messages_to_window(msgs, None, 8192, 8192)
    assert kept == msgs


def test_a_prompt_larger_than_the_window_is_still_trimmed():
    msgs = _node_history(rounds=12, chars=6000)   # ~20k tokens
    kept = InferenceRouter._cap_messages_to_window(msgs, None, 8192, 8192)
    assert len(kept) < len(msgs)
    assert kept[0] == msgs[0] and kept[-1] == msgs[-1]


def _no_orphan_tool_results(msgs):
    """Every tool result follows an assistant message that made tool calls."""
    for i, m in enumerate(msgs):
        if m.get("role") == "tool":
            j = i - 1
            while j >= 0 and msgs[j].get("role") == "tool":
                j -= 1
            if j < 0 or msgs[j].get("role") != "assistant" or not msgs[j].get("tool_calls"):
                return False
    return True


def test_the_cap_never_leaves_a_tool_result_without_its_call():
    """Live browser task 2026-10-02: the cap dropped an assistant tool call and
    kept its result - the provider answered 400 "Message has tool role, but
    there was no previous assistant message with a tool call"."""
    # Sweep sizes: the old cap orphaned a result only when the budget was met
    # right after it dropped an assistant call, so a few fixed sizes can miss it.
    cases = [(r, c, w) for r in (3, 6, 10) for c in range(800, 9000, 400) for w in (4096, 8192)]
    for rounds, chars, window in cases:
        msgs = _node_history(rounds=rounds, chars=chars)
        kept = InferenceRouter._cap_messages_to_window(msgs, None, window, 8192)
        assert _no_orphan_tool_results(kept), (rounds, chars, [m.get("role") for m in kept])
        assert kept[-1] == msgs[-1]
