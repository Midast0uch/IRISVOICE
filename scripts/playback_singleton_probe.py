"""Probe: does the REAL streaming TTS path open two PortAudio streams at once?

Its purpose is to test the 2026-10-13 access-violation fix at the NATIVE
boundary, not at a mock boundary. It drives the real
``IRISGateway._speak_response`` streaming playback path from several concurrent
threads against a REAL sounddevice device, and counts concurrently-open real
``OutputStream`` objects.

Run it in a subprocess: a native access violation (the original bug) then
surfaces as an exit code, not as a dead test run.

Exit codes:
  0  one stream at a time; the process survived
  2  two or more streams were open at once (the crash condition)
  3  skip - no usable output device

A Windows access violation (0xC0000005) surfaces as exit code 3221225477.

Usage:
  python scripts/playback_singleton_probe.py --iterations 3 --concurrency 2
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import queue
import sys
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

# Make ``backend`` importable when this file is run directly as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import sounddevice as sd


EVENTS: list = []
_EV_LOCK = threading.Lock()
_T0 = time.monotonic()


def _ev(what: str) -> None:
    with _EV_LOCK:
        EVENTS.append(
            (round(time.monotonic() - _T0, 4), threading.current_thread().name, what)
        )


class CountingStream(sd.OutputStream):
    """The REAL OutputStream, with a counter over concurrently-open streams.

    The open/close flags are PER INSTANCE, never ``id(self)``: CPython reuses
    object ids after GC, so an id-keyed "already closed" set silently misses a
    close and inflates the concurrent count (measured: a false OVERLAP).
    """

    _lock = threading.Lock()
    active = 0
    max_active = 0
    opens = 0
    closes = 0

    def __init__(self, *args, **kwargs):
        self._probe_open = False
        self._probe_closed = False
        super().__init__(*args, **kwargs)
        with CountingStream._lock:
            CountingStream.active += 1
            CountingStream.opens += 1
            CountingStream.max_active = max(
                CountingStream.max_active, CountingStream.active
            )
            self._probe_open = True
            _ev(f"stream OPEN   active={CountingStream.active}")

    def close(self):  # type: ignore[override]
        try:
            super().close()
        finally:
            if getattr(self, "_probe_open", False) and not getattr(
                self, "_probe_closed", False
            ):
                with CountingStream._lock:
                    CountingStream.active -= 1
                    CountingStream.closes += 1
                    self._probe_closed = True
                    _ev(f"stream CLOSE  active={CountingStream.active}")


def _pick_device(name_substr: str):
    """First output device whose name contains ``name_substr``, else the default."""
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        if d["max_output_channels"] > 0 and name_substr.lower() in d["name"].lower():
            return i
    try:
        default_out = sd.default.device[1]
        if default_out is not None and default_out >= 0:
            return int(default_out)
    except Exception:
        pass
    for i, d in enumerate(devices):
        if d["max_output_channels"] > 0:
            return i
    return None


def _run_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


def build_gateway():
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
    gw._logger = logging.getLogger("playback-probe")
    gw._main_loop = asyncio.new_event_loop()
    threading.Thread(target=_run_loop, args=(gw._main_loop,), daemon=True).start()
    return gw


def build_engine():
    pipeline = MagicMock()
    pipeline._native_available = False
    pipeline._native_player = None
    engine = MagicMock()
    engine.is_speech_interrupted = MagicMock(return_value=False)
    engine.pipeline = pipeline
    return engine


def build_tts(chunk_frames: int = 2400, chunks: int = 2):
    tts = MagicMock()
    tts.is_loaded.return_value = True

    def _synthesize(chunk, sample_rate=24000, **kw):
        for _ in range(chunks):
            yield np.zeros(chunk_frames, dtype=np.float32)
            time.sleep(0.01)

    tts.synthesize_stream.side_effect = _synthesize
    return tts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=3)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--device-index", type=int, default=None)
    ap.add_argument("--device-name", default="CABLE Input")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    dev = (
        args.device_index
        if args.device_index is not None
        else _pick_device(args.device_name)
    )
    if dev is None or sd.query_devices(dev)["max_output_channels"] < 1:
        print(json.dumps({"status": "skip", "reason": "no usable output device"}))
        return 3

    # Redirect the implicit default output to the (silent) probe device.
    sd.default.device = (-1, dev)

    gw = build_gateway()
    engine = build_engine()
    # End each call as soon as its stream is open. The 1 s "late interrupt" tail
    # runs INSIDE the lock and is not what this probe measures; skipping it
    # keeps the run short. The stream still really opens and closes.
    engine.is_speech_interrupted = lambda: CountingStream.active > 0
    tts = build_tts()

    import backend.audio.pipeline as _pl

    _orig_acq = _pl.acquire_playback_device
    _orig_rel = _pl.release_playback_device

    def _acq(timeout=None):
        t0 = time.monotonic()
        got = _orig_acq(timeout)
        _ev(f"LOCK acquire got={got} waited={time.monotonic() - t0:.3f}")
        return got

    def _rel():
        _ev("LOCK release")
        return _orig_rel()

    _pl.acquire_playback_device = _acq
    _pl.release_playback_device = _rel

    errors: list = []

    def one_call(i: int) -> None:
        q: queue.Queue = queue.Queue()
        q.put("hello world this is a probe sentence")
        q.put(None)
        try:
            gw._speak_response(input_source=q, session_id=None)
        except BaseException as exc:  # noqa: BLE001 - probe records, never hides
            errors.append(f"{type(exc).__name__}: {exc}")

    with (
        patch("backend.agent.get_tts_manager", return_value=tts),
        patch("backend.agent.tts.get_tts_manager", return_value=tts),
        patch("backend.audio.engine.get_audio_engine", return_value=engine),
        patch("sounddevice.OutputStream", CountingStream),
    ):
        for _ in range(args.iterations):
            threads = [
                threading.Thread(target=one_call, args=(i,), daemon=True)
                for i in range(args.concurrency)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

    result = {
        "status": "ok",
        "sounddevice": sd.__version__,
        "portaudio": sd.get_portaudio_version()[1],
        "device_index": dev,
        "device_name": sd.query_devices(dev)["name"],
        "iterations": args.iterations,
        "concurrency": args.concurrency,
        "stream_opens": CountingStream.opens,
        "stream_closes": CountingStream.closes,
        "max_concurrent_streams": CountingStream.max_active,
        "errors": errors,
    }
    if args.debug:
        print("--- timeline ---", file=sys.stderr)
        for ts, th, what in sorted(EVENTS):
            print(f"  {ts:8.4f}  {th:14s}  {what}", file=sys.stderr)

    if CountingStream.max_active > 1:
        result["status"] = "OVERLAP"
        print(json.dumps(result))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
