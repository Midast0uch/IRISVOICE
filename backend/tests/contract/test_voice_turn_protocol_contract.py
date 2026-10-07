"""Contract: a voice turn reaches the frontend as ONE turn, not four couriers.

The wake word, the microphone and the speech recognizer are not needed here.
`_on_voice_result` hands `_process_voice_transcription` a plain transcript, so
the whole reply path after transcription can be driven from a test: the turn
framing, the user bubble, the answer, the spoken line, and the error case.

What is stubbed, and why each is not the thing under test:
  * the WS manager (captures the frames) - the wire is the assertion;
  * `get_agent_kernel` (a stub that streams a fixed reply) - no model in a test;
  * `_enqueue_reply` (TTS playback) - no audio device in a test; the SPOKEN LINE
    is asserted on turn.end, which is what the frontend highlights;
  * `data/STTPROC.wav` (absent) - the "processing" chime must not open a device;
  * `get_ask_user_tool` - no pending question in this scenario.

What is NOT stubbed: `_process_voice_transcription` and `TurnEmitter` run for
real. Under the STAND-INS rule, a test that re-implements the logic it claims
to guard is the defect this file exists to remove - the old
`test_chunk_callback_fix.TestFullVoicePipelineNonStreaming` copied the sentence
queue into the test file and so could pass while the gateway broke.

Guard: fails on the pre-retirement code, which sent `chat_chunk`,
`chat_reasoning`, the assistant `text_response` and the final `chat_message`
for this same turn.
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
    """Captures what the gateway would send to the one connected client."""

    def __init__(self):
        self.sent: list[dict] = []
        self._loop = None

    def bind(self, loop):
        self._loop = loop

    async def send_to_client(self, client_id, msg, *a, **kw):
        self.sent.append(msg)
        return True

    async def broadcast(self, msg, **kw):
        return None

    async def broadcast_to_session(self, session_id, msg, **kw):
        return None

    def buffer_message(self, session_id, msg):
        self.sent.append(msg)

    # helpers for the assertions
    def types(self):
        return [m.get("type") for m in self.sent]

    def of_type(self, kind):
        return [m for m in self.sent if m.get("type") == kind]


class _StubKernel:
    """A kernel that streams a fixed reply and derives a short spoken line."""

    _tool_bridge = object()
    _pending_thinking = ""

    def __init__(self, reply=REPLY, boom=None):
        self._reply = reply
        self._boom = boom
        self.calls: list[dict] = []

    def process_text_message(self, text, **kw):
        self.calls.append(kw)
        if self._boom:
            raise self._boom
        cb = kw.get("chunk_callback")
        if cb:
            # Stream in two deltas, like a real provider, so the part path runs.
            cb(self._reply[: len(self._reply) // 2])
            cb(self._reply[len(self._reply) // 2:])
            cb("")  # the force-flush sentinel
        return self._reply

    def prepare_spoken_text(self, full_response, user_message=""):
        return "Two plus two is four."


def _gateway(wire, kernel, monkeypatch):
    """A gateway with only the hardware and the model replaced."""
    gw = IRISGateway.__new__(IRISGateway)
    gw._logger = logging.getLogger("test.voice_turn")
    gw._ws_manager = wire
    gw._active_conversation_id = {"iris": "conv-voice"}
    gw._active_voice_client = {"iris": "cli-1"}
    gw._conversation_sessions = set()
    gw._playback_event = threading.Event()
    gw._voice_timing = {"vad_end": 0.0}
    # TTS: record the line instead of playing it (no audio device in a test).
    spoken_lines: list[str] = []
    gw._enqueue_reply = lambda **kw: spoken_lines.extend(
        [kw.get("text")] if kw.get("text") else []
    )
    gw._send_voice_typing = lambda *a, **kw: None
    gw._matches_stop_listening = lambda *a, **kw: False
    # No pending question card in this scenario.
    import backend.agent.tools.ask_user_tool as _ask

    monkeypatch.setattr(_ask, "get_ask_user_tool", lambda: SimpleNamespace(
        resolve_via_voice=lambda *a, **kw: {"handled": False}
    ))
    # No "processing" chime: sounddevice must never open a device in a test.
    _real_isfile = os.path.isfile

    monkeypatch.setattr(
        os.path, "isfile",
        lambda p: False if str(p).endswith("STTPROC.wav") else _real_isfile(p),
    )
    import backend.agent.agent_kernel as _ak

    monkeypatch.setattr(_ak, "get_agent_kernel", lambda *a, **kw: kernel)
    return gw, spoken_lines


async def _await_frames(wire, needed, timeout=2.0):
    """Let the loop deliver the turn frames.

    The turn's parts are handed to the loop with run_coroutine_threadsafe from
    the executor thread that runs the kernel, so they arrive a tick or two
    AFTER the pipeline coroutine returns. Waiting here keeps the assertions
    about the WIRE, not about scheduling luck.
    """
    import time as _time

    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        if all(kind in wire.types() for kind in needed):
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"frames never arrived: {wire.types()} (wanted {needed})")


@pytest.mark.asyncio
async def test_a_voice_turn_is_one_turn_with_no_legacy_courier(monkeypatch):
    """The DONE line: a voice turn is turn.start / numbered parts / exactly one
    turn.end, and none of the retired reply frames goes out."""
    wire = _Wire()
    kernel = _StubKernel()
    gw, _spoken = _gateway(wire, kernel, monkeypatch)
    wire.bind(asyncio.get_running_loop())

    await gw._process_voice_transcription("iris", "cli-1", TRANSCRIPT, "")
    await _await_frames(wire, ["turn.end"])

    types = wire.types()
    assert types.count("turn.start") == 1, types
    assert types.count("turn.end") == 1, types
    # The TURN frames run start -> parts -> end. The user-echo `text_response`
    # is NOT part of that sequence (it is the transcript bubble, sent directly,
    # before the kernel runs), so the ordering is asserted over the turn frames
    # alone: types[0] == types[-1] would wrongly fail on the echo.
    turn_seq = [t for t in types if t.startswith("turn.")]
    assert turn_seq[0] == "turn.start", turn_seq
    assert turn_seq[-1] == "turn.end", turn_seq
    assert turn_seq.count("turn.end") == 1, turn_seq
    # Dense seq numbers 1..N.
    seqs = [p["payload"]["seq"] for p in wire.of_type("turn.part")]
    assert seqs == list(range(1, len(seqs) + 1)), seqs

    # The answer rides the parts and the end, with the spoken line on the end.
    texts = [
        p["payload"]["part"]["delta"]
        for p in wire.of_type("turn.part")
        if p["payload"]["part"]["type"] == "text"
    ]
    assert "".join(texts).strip() == REPLY, texts
    end = wire.of_type("turn.end")[0]["payload"]
    assert end["status"] == "ok" and end["text"] == REPLY and end["speak"]
    assert end["turn_id"], "the end must name its turn"

    # THE RETIREMENT: none of these four may leave the gateway for this turn.
    for gone in ("chat_chunk", "chat_reasoning", "chat_message"):
        assert gone not in types, f"{gone} is still sent for a voice reply"
    assert not [
        m for m in wire.of_type("text_response")
        if (m.get("payload") or {}).get("sender") == "assistant"
        or m.get("sender") == "assistant"
    ], "the assistant text_response courier is still sent"

    # The user bubble IS still a legacy frame, by design (voice echo, kept).
    echo = [
        m for m in wire.of_type("text_response")
        if (m.get("payload") or {}).get("sender") == "user"
    ]
    assert len(echo) == 1 and echo[0]["payload"]["text"] == TRANSCRIPT, echo


@pytest.mark.asyncio
async def test_a_failed_voice_turn_shows_the_error_and_ends_once(monkeypatch):
    """An LLM failure must be VISIBLE: a friendly line as the turn's error, one
    turn.end with status error, and no empty assistant bubble."""
    wire = _Wire()
    kernel = _StubKernel(boom=RuntimeError("429 upstream"))
    gw, _spoken = _gateway(wire, kernel, monkeypatch)
    wire.bind(asyncio.get_running_loop())

    await gw._process_voice_transcription("iris", "cli-1", TRANSCRIPT, "")
    await _await_frames(wire, ["turn.end"])

    types = wire.types()
    assert types.count("turn.end") == 1, types
    end = wire.of_type("turn.end")[0]["payload"]
    assert end["status"] == "error", end
    err_parts = [
        p["payload"]["part"]
        for p in wire.of_type("turn.part")
        if p["payload"]["part"]["type"] == "error"
    ]
    assert len(err_parts) == 1, "the failure must be a visible error part"
    assert "trouble connecting" in err_parts[0]["message"], err_parts
    assert not wire.of_type("chat_message"), "an empty bubble was drawn"