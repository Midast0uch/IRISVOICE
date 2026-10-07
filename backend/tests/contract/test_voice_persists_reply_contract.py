"""Contract: a VOICE turn persists its reply (live 2026-10-07).

Live: a voice turn delivered and SPOKE its reply, and its task card persisted,
but the reply itself was never written to conversations.db — so after a reload
the chat showed an orphan "DONE" card with no reply beside it. The database
held 0 messages for the turn whose card was still on screen.

The WS text path has persisted since 2026-08-12 (source "ws_text_message"); the
voice path had NO persistence call anywhere in _process_voice_transcription.

This drives the REAL _process_voice_transcription with a stubbed kernel (no
model, no audio device) and asserts the reply reaches the store. Fails on the
pre-fix gateway: 0 messages.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from types import SimpleNamespace

import pytest

from backend.iris_gateway import IRISGateway


TRANSCRIPT = "what is two plus two"
REPLY = "Two plus two is four."


class _Wire:
    def __init__(self):
        self.sent = []

    async def send_to_client(self, client_id, msg, *a, **kw):
        self.sent.append(msg)
        return True

    async def broadcast(self, msg, **kw):
        return None

    async def broadcast_to_session(self, session_id, msg, **kw):
        return None

    def buffer_message(self, session_id, msg):
        self.sent.append(msg)

    def types(self):
        return [m.get("type") for m in self.sent]


class _StubKernel:
    _tool_bridge = object()
    _pending_thinking = ""

    def process_text_message(self, text, **kw):
        cb = kw.get("chunk_callback")
        if cb:
            cb(REPLY)
            cb("")
        return REPLY

    def prepare_spoken_text(self, full_response, user_message=""):
        return "Two plus two is four."


def _gateway(wire, monkeypatch):
    gw = IRISGateway.__new__(IRISGateway)
    gw._logger = logging.getLogger("test.voice_persist")
    gw._ws_manager = wire
    gw._active_conversation_id = {"iris": "conv-voice"}
    gw._active_voice_client = {"iris": "cli-1"}
    gw._conversation_sessions = set()
    gw._playback_event = threading.Event()
    gw._enqueue_reply = lambda **kw: None
    gw._send_voice_typing = lambda *a, **kw: None
    gw._matches_stop_listening = lambda *a, **kw: False

    import backend.agent.tools.ask_user_tool as _ask

    monkeypatch.setattr(_ask, "get_ask_user_tool", lambda: SimpleNamespace(
        resolve_via_voice=lambda *a, **kw: {"handled": False}
    ))
    _real_isfile = os.path.isfile
    monkeypatch.setattr(
        os.path, "isfile",
        lambda p: False if str(p).endswith("STTPROC.wav") else _real_isfile(p),
    )
    import backend.agent.agent_kernel as _ak

    monkeypatch.setattr(_ak, "get_agent_kernel", lambda *a, **kw: _StubKernel())
    return gw


async def _drain(wire, kind, timeout=2.0):
    import time as _t

    deadline = _t.monotonic() + timeout
    while _t.monotonic() < deadline:
        if kind in wire.types():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"{kind} never arrived: {wire.types()}")


@pytest.mark.asyncio
async def test_a_voice_reply_reaches_the_conversation_store(tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_CONVERSATIONS_DB", str(tmp_path / "conversations.db"))
    import importlib

    import backend.conversation_store as cs

    importlib.reload(cs)

    conv = cs.create_conversation(title="voice persist")["id"]

    wire = _Wire()
    gw = _gateway(wire, monkeypatch)

    await gw._process_voice_transcription("iris", "cli-1", TRANSCRIPT, "",
                                          conversation_id=conv)
    await _drain(wire, "turn.end")

    # The turn itself is unchanged: one start, one end, and the reply is on it.
    types = wire.types()
    assert types.count("turn.start") == 1, types
    assert types.count("turn.end") == 1, types
    end = [m for m in wire.sent if m["type"] == "turn.end"][0]["payload"]
    assert end["status"] == "ok" and end["text"] == REPLY

    # THE FIX: the reply is in the store, so a reload keeps it beside its card.
    texts = [m["text"] for m in cs.get_conversation(conv)["messages"]]
    assert REPLY in texts, (
        f"voice reply was not persisted (store holds {texts!r}) - the card "
        "survives a reload and would be left orphaned"
    )
    stored = [m for m in cs.get_conversation(conv)["messages"]
              if m["text"] == REPLY]
    assert stored[0]["role"] == "assistant"
    assert stored[0].get("turn_id"), "the stored reply must name its turn"