"""
test_narration_broadcast.py — verifies the agent narration unification fix.

The fix makes agent-initiated speech (SpeakTool / fillers / background
narration) drive the SAME frontend narration contract the main LLM response
path uses (audio_envelope phase speaking->idle + listening_state
speaking->idle), and serializes playback via a shared lock so an utterance
can never be cut off by — or cut off — another utterance or the response
stream.

These are BEHAVIORAL tests: they assert the actual WS events emitted and the
actual serialization, not just "doesn't crash".
"""

import sys
import os
import threading
import time
import logging
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _make_kernel(broadcast_collector=None):
    """Build a ConversationKernel wired to mock TTS + audio pipeline.

    broadcast_collector, if given, receives (session_id, msg) tuples — the
    exact signature of the wired broadcaster callable.
    """
    from backend.agent.conversation_kernel import ConversationKernel

    tts = MagicMock()
    tts.synthesize_stream = MagicMock(return_value=iter([1, 2, 3]))
    tts.stop = MagicMock()

    pipeline = MagicMock()
    pipeline.play_stream = MagicMock()

    if broadcast_collector is not None:
        broadcaster = lambda sid, msg: broadcast_collector.append((sid, msg))
    else:
        broadcaster = None

    kernel = ConversationKernel(
        voice_handler=MagicMock(),
        tts_manager=tts,
        audio_pipeline=pipeline,
        session_id_getter=lambda: "sess-1",
        broadcast_event=broadcaster,
    )
    # The kernel reads tts from self._tts_manager and pipeline from
    # self._resolve_audio_pipeline() (which returns self._audio_pipeline).
    kernel._tts_manager = tts
    kernel._audio_pipeline = pipeline
    return kernel


def test_speak_utterance_broadcasts_speaking_then_idle():
    """Agent speech must emit the SAME contract as a normal response:
    listening_state speaking + audio_envelope speaking, then both idle.
    Order matters: speaking must precede idle so the orb animates correctly.
    """
    collector = []
    kernel = _make_kernel(collector)

    kernel._speak_utterance("hello there", interrupt=False)

    # Flatten to (type, state-or-phase) pairs
    seen = [
        (msg.get("type"), msg.get("payload", {}).get("state") or msg.get("payload", {}).get("phase"))
        for _, msg in collector
    ]
    assert ("listening_state", "speaking") in seen, f"missing listening_state:speaking in {seen}"
    assert ("listening_state", "idle") in seen, f"missing listening_state:idle in {seen}"
    assert ("audio_envelope", "speaking") in seen, f"missing audio_envelope:speaking in {seen}"
    assert ("audio_envelope", "idle") in seen, f"missing audio_envelope:idle in {seen}"

    # speaking must come before idle for both channels
    assert seen.index(("listening_state", "speaking")) < seen.index(("listening_state", "idle"))
    assert seen.index(("audio_envelope", "speaking")) < seen.index(("audio_envelope", "idle"))

    # Playback actually happened
    kernel._audio_pipeline.play_stream.assert_called_once()


def test_speak_utterance_serializes_playback():
    """The shared narration lock must prevent two utterances from playing
    concurrently — this is the actual cut-off fix.  If playback overlapped,
    the orb/audio would glitch and one utterance could be truncated.
    """
    kernel = _make_kernel(None)

    active = {"n": 0}
    max_concurrent = {"n": 0}
    counter_lock = threading.Lock()

    def play_stream(stream, sample_rate=None):
        with counter_lock:
            active["n"] += 1
            max_concurrent["n"] = max(max_concurrent["n"], active["n"])
        time.sleep(0.1)  # simulate real playback duration
        with counter_lock:
            active["n"] -= 1

    kernel._audio_pipeline.play_stream = play_stream

    t1 = threading.Thread(target=kernel._speak_utterance, args=("one", False))
    t2 = threading.Thread(target=kernel._speak_utterance, args=("two", False))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert max_concurrent["n"] == 1, (
        f"play_stream ran concurrently (max={max_concurrent['n']}) — "
        f"narration lock is not serializing playback"
    )


def test_speak_utterance_no_broadcast_when_unwired():
    """If no broadcaster is wired (e.g. a test/headless env), the utterance
    must still play without raising — broadcast is best-effort."""
    kernel = _make_kernel(None)  # broadcast_event=None
    # Should not raise
    kernel._speak_utterance("silent world", interrupt=False)
    kernel._audio_pipeline.play_stream.assert_called_once()


def test_gateway_wires_narration_broadcaster():
    """iris_gateway.set_voice_handler must wire the narration broadcaster
    (the callable that forwards agent speech to the WS session) into the
    ConversationKernel, so agent speech reaches the frontend.
    """
    from backend.iris_gateway import IRISGateway
    from backend.agent.conversation_kernel import ConversationKernel

    mock_ws = MagicMock()
    mock_state = MagicMock()
    vh = MagicMock()
    vh.set_command_result_callback = MagicMock()
    vh._active_session_id = "default"
    vh.set_audio_level_callback = MagicMock()

    with (
        patch("backend.iris_gateway.get_websocket_manager", return_value=mock_ws),
        patch("backend.iris_gateway.get_state_manager", return_value=mock_state),
        patch("backend.iris_gateway.WakeWordDiscovery"),
        patch("backend.iris_gateway.CleanupAnalyzer"),
        patch("backend.iris_gateway.LFMVLProvider"),
        patch("backend.iris_gateway.get_tts_manager", return_value=MagicMock()),
        patch("backend.iris_gateway.threading.Thread"),
        patch("backend.agent.conversation_kernel.set_conversation_kernel") as mock_set,
        patch("backend.agent.conversation_kernel.get_conversation_kernel", return_value=None),
        patch.object(ConversationKernel, "subscribe_to_event_bus"),
        patch("backend.agent.tools.speak_broadcaster.get_speak_broadcaster", return_value=MagicMock()),
    ):
        gw = IRISGateway.__new__(IRISGateway)
        gw._ws_manager = mock_ws
        gw._state_manager = mock_state
        gw._logger = logging.getLogger("test")
        gw._voice_handler = None
        gw._main_loop = None
        gw._conversation_sessions = set()
        gw._sleeping_sessions = set()
        gw._active_voice_client = {}
        gw._audio_pipeline = MagicMock()
        gw._relisten_pre_speech_timeout = 8.0

        gw.set_voice_handler(vh)

        created_kernel = mock_set.call_args[0][0]
        assert created_kernel._broadcast_event is not None, (
            "narration broadcaster must be wired into the ConversationKernel"
        )


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
