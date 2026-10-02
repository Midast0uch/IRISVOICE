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
