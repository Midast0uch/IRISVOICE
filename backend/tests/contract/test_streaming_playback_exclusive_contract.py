"""The streaming TTS path holds the process-wide playback lock (2026-10-16).

``_speak_response`` opens its own ``sounddevice.OutputStream``. The lock in
``backend/audio/pipeline.py`` ("one utterance on the audio device at a time")
already guarded ``AudioPipeline.play_stream`` / ``play_audio``, but the streaming
path bypassed it. Two streams alive at once — the lane scheduler retrying a
wedged node while its play thread was still inside ``Pa_WriteStream``, or a
second session speaking — corrupted PortAudio's native state and killed the
backend with an access violation in ``_raw_write`` (``logs/crash_traceback.log``
2026-10-13: two ``speech-lane-play-*`` threads for one node). This file pins the
invariant ON the streaming path.

``test_streaming_path_skips_when_device_is_busy`` fails on the pre-fix code:
``_speak_response`` opened its OutputStream (``stream_cls.call_count == 1``)
while the device was already held.
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

from backend.audio import pipeline as pl


def _make_mock_gateway():
    from backend.iris_gateway import IRISGateway

    gw = IRISGateway.__new__(IRISGateway)
    ws = MagicMock()
    ws.broadcast = AsyncMock()
    ws.broadcast_to_session = AsyncMock()
    ws.send_to_client = AsyncMock()
    gw._ws_manager = ws
    gw._state_manager = MagicMock()
    gw._agent_kernels = {}
    gw._conversation_sessions = set()
    gw._active_voice_client = {}
    gw._relisten_pre_speech_timeout = 8.0
    gw._tts_prewarmed = True
    gw._speech_interrupted = False
    gw._word_monitor_stop = threading.Event()
    gw._word_monitor_thread = None
    gw._logger = logging.getLogger("test-streaming-playback")
    gw._main_loop = asyncio.new_event_loop()

    def _run_loop():
        asyncio.set_event_loop(gw._main_loop)
        gw._main_loop.run_forever()

    lt = threading.Thread(target=_run_loop, daemon=True)
    lt.start()
    gw._loop_thread = lt
    return gw


def _make_mock_pipeline():
    pipeline = MagicMock()
    pipeline._native_available = False
    pipeline._native_player = None
    return pipeline


def _make_mock_engine(pipeline):
    engine = MagicMock()
    engine.is_speech_interrupted = MagicMock(return_value=False)
    engine.pipeline = pipeline
    return engine


def _mock_tts():
    tts = MagicMock()
    tts.is_loaded.return_value = True

    def _synthesize(chunk, sample_rate=24000, **kw):
        for _ in range(3):
            yield np.zeros(2400, dtype=np.float32)
            time.sleep(0.01)

    tts.synthesize_stream.side_effect = _synthesize
    return tts


def test_streaming_path_skips_when_device_is_busy(monkeypatch):
    """While another utterance holds the device, the streaming path must NOT
    open a second OutputStream. It logs and returns; the process survives."""
    gw = _make_mock_gateway()
    engine = _make_mock_engine(_make_mock_pipeline())
    tts = _mock_tts()

    monkeypatch.setattr(pl, "_PLAYBACK_WAIT_S", 0.2)
    assert pl.acquire_playback_device(timeout=1.0), "test could not take the lock"
    try:
        with (
            patch("backend.agent.get_tts_manager", return_value=tts),
            patch("backend.agent.tts.get_tts_manager", return_value=tts),
            patch("backend.audio.engine.get_audio_engine", return_value=engine),
            patch("sounddevice.OutputStream") as stream_cls,
        ):
            stream_cls.return_value = MagicMock()
            q: queue.Queue = queue.Queue()
            q.put("hello world")
            q.put(None)
            gw._speak_response(input_source=q, session_id=None)
            assert stream_cls.call_count == 0, (
                "the streaming path opened a second OutputStream while the "
                "device was held — the access-violation condition"
            )
    finally:
        pl.release_playback_device()
        gw._main_loop.call_soon_threadsafe(gw._main_loop.stop)


def test_streaming_path_releases_the_device_after_playback(monkeypatch):
    """A normal streaming utterance frees the device when it returns."""
    gw = _make_mock_gateway()
    engine = _make_mock_engine(_make_mock_pipeline())
    tts = _mock_tts()
    monkeypatch.setattr(pl, "_PLAYBACK_WAIT_S", 1.0)

    with (
        patch("backend.agent.get_tts_manager", return_value=tts),
        patch("backend.agent.tts.get_tts_manager", return_value=tts),
        patch("backend.audio.engine.get_audio_engine", return_value=engine),
        patch("sounddevice.OutputStream") as stream_cls,
    ):
        stream_cls.return_value = MagicMock()
        q: queue.Queue = queue.Queue()
        q.put("hello world")
        q.put(None)
        try:
            gw._speak_response(input_source=q, session_id=None)
        finally:
            gw._main_loop.call_soon_threadsafe(gw._main_loop.stop)

    assert pl._PLAYBACK_LOCK.acquire(timeout=1.0), (
        "the streaming path leaked the playback lock"
    )
    pl._PLAYBACK_LOCK.release()
