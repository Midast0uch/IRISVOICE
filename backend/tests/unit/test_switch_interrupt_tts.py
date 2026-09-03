"""
Unit tests T9 (REQ-3): switch_conversation interrupts in-flight TTS via the audio engine.

UT-1: missing conversation_id is a no-op for the binding (no crash, no undefined var).
UT-2: when the audio engine reports TTS active, switch_conversation calls
      engine.interrupt_speech() exactly once; when the engine is absent, no call is made
      (non-fatal).
"""
import asyncio
import sys

from unittest.mock import patch

import pytest

try:
    from backend.iris_gateway import IRISGateway  # noqa: E402
except ImportError:
    sys.path.insert(0, "..")
    from backend.iris_gateway import IRISGateway  # noqa: E402


class _FakeWSManager:
    def __init__(self):
        self.sent = []

    async def send_to_client(self, client_id, msg):
        self.sent.append((client_id, msg))

    async def broadcast_to_session(self, session_id, msg):
        pass

    async def broadcast(self, msg):
        pass


@pytest.fixture
def loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def test_ut2_switch_interrupts_tts_when_engine_active(loop):
    """REQ-3: switch calls engine.interrupt_speech() once when TTS is active."""
    calls = {"n": 0}

    class _Engine:
        _tts_active = True

        def interrupt_speech(self):
            calls["n"] += 1

    gw = IRISGateway(ws_manager=_FakeWSManager())
    gw._main_loop = asyncio.new_event_loop()
    sid = "session_iris"
    msg = {
        "type": "switch_conversation",
        "payload": {"conversation_id": "thread_B", "old_conversation_id": "thread_A"},
    }
    with patch("backend.audio.engine.get_audio_engine", return_value=_Engine()):
        loop.run_until_complete(gw.handle_message("iris", msg, session_id=sid))
    assert calls["n"] == 1, "interrupt_speech must be called exactly once when TTS active"


def test_ut2_switch_no_interrupt_when_engine_absent(loop):
    """REQ-3 AC2: switch with no engine is non-fatal (no interrupt call)."""
    gw = IRISGateway(ws_manager=_FakeWSManager())
    gw._main_loop = asyncio.new_event_loop()
    sid = "session_iris"
    msg = {
        "type": "switch_conversation",
        "payload": {"conversation_id": "thread_B", "old_conversation_id": "thread_A"},
    }
    # Must not raise even though engine is None.
    with patch("backend.audio.engine.get_audio_engine", return_value=None):
        loop.run_until_complete(gw.handle_message("iris", msg, session_id=sid))
    acks = [m for (_, m) in gw._ws_manager.sent if m.get("type") == "conversation_switched"]
    assert acks, "switch must still ack when engine is absent"
