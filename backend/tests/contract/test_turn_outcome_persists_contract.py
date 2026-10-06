"""A stopped or failed text turn keeps its outcome line after a reload.

Live 2026-10-06: the turn store is memory-only; after a reload a Stopped turn
showed only its prompt. The gateway now saves the same plain line the chat
shows to the turn's own conversation, on the cancel and the error path.

Guard: fails on the old gateway (no _persist_turn_outcome; the ends saved nothing).
"""
from __future__ import annotations

import importlib
import inspect
import logging


def test_the_outcome_line_is_saved_to_the_frames_conversation(tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_CONVERSATIONS_DB", str(tmp_path / "conversations.db"))
    import backend.conversation_store as cs

    importlib.reload(cs)
    from backend.iris_gateway import IRISGateway, _STOPPED_LINE

    strand = cs.create_conversation(title="side check")["id"]
    other = cs.create_conversation(title="root")["id"]

    class _Stub:
        _active_conversation_id = {"sess": other}  # stale mapping: must NOT win
        _logger = logging.getLogger("test")

    IRISGateway._persist_turn_outcome(
        _Stub(), {"conversation_id": strand}, "sess", "sess", "turn-1", _STOPPED_LINE
    )
    msgs = cs.get_conversation(strand)["messages"]
    assert [m["text"] for m in msgs] == [_STOPPED_LINE]
    assert cs.get_conversation(other)["messages"] == []


def test_both_the_cancel_and_the_error_end_save_the_outcome():
    from backend.iris_gateway import IRISGateway

    src = inspect.getsource(IRISGateway)
    i_err = src.index('_turn.end("error", error=friendly)')
    assert "_persist_turn_outcome(" in src[i_err:i_err + 300]
    i_can = src.index('_turn.end("cancelled", error="cancelled")')
    assert "_persist_turn_outcome(" in src[i_can:i_can + 300]


def test_a_stopped_turn_stays_quiet_on_both_chunk_paths():
    """Live 2026-10-06: after Stop, the executor thread (not cancellable) still
    streamed its reply through chat_chunk and drew an empty IRIS entry. Both
    chunk callbacks drop text once their turn has ended. Fails on the old code."""
    from backend.iris_gateway import IRISGateway

    src = inspect.getsource(IRISGateway)
    for start in ("def chunk_callback(chunk: str):", "def _chunk_cb(chunk: str):"):
        body = src[src.index(start):]
        body = body[: body.index('"chat_chunk"')]
        assert "if _turn.ended:" in body, f"{start} sends chunks after the turn ended"
