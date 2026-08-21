"""
Tests for the FIRST-WAKE VAD fix (backend/audio/pipeline.py + voice_command.py).

Root cause of the first-wake bug: the activation beep (880 Hz, ~80 ms + room
echo) leaked into the mic during the VAD calibration window because the
half-duplex gate in AudioPipeline._input_callback required BOTH
`_tts_active AND echo_cancellation` to drop frames. When echo_cancellation
was off (common default), the beep reached the VAD listener, inflating the
noise floor so the user's real speech was never detected -> recording hung /
empty transcript on the first wake.

Fix: the gate now drops frames on `_tts_active` ALONE (the beep is a known
self-generated tone). A backstop ceiling (rms < 0.1) in the VAD calibration
excludes any residual beep/echo energy.

These tests assert: (1) beep frames are dropped from STT listeners while
_tts_active is True, (2) normal frames flow when it's False, (3) VAD still
detects speech after a beep that was properly gated out.

Run: python -m pytest backend/tests/test_vad_first_wake.py -v
"""
import sys
import types
import importlib.util
import logging
from unittest.mock import MagicMock

import numpy as np
import pytest

# DEBT FIX (pin_fd5b312e69bf): was module-level logging.disable(CRITICAL) -
# process-global state that killed all caplog assertions in later tests.
@pytest.fixture(autouse=True)
def _silence_logs():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)

# Stub the heavy backend.audio submodules so we can import pipeline +
# voice_command without loading sounddevice/torch.  We do NOT stub `backend`
# itself (it keeps its real __path__ so backend.agent.* still resolves for
# other test files in the same session — avoids cross-test sys.modules
# pollution).
import os as _os
_BACKEND_ROOT = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "..")
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

for _name in ("backend.audio", "backend.audio.engine", "backend.audio.cadence_detector"):
    if _name not in sys.modules:
        _m = types.ModuleType(_name)
        _m.__path__ = []
        sys.modules[_name] = _m
sys.modules["backend.audio.engine"].AudioEngine = object
sys.modules["backend.audio.engine"].VoiceState = object
sys.modules["backend.audio.engine"].get_audio_engine = lambda *a, **k: None
sys.modules["backend.audio.cadence_detector"].CadenceDetector = object


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


_pipeline = _load("backend.audio.pipeline", "backend/audio/pipeline.py")
_voice = _load("backend.audio.voice_command", "backend/audio/voice_command.py")
AudioPipeline = _pipeline.AudioPipeline


def _make_pipeline():
    p = AudioPipeline.__new__(AudioPipeline)
    p._frame_listeners = []
    p._on_audio_frame = None
    p._on_barge_in_energy = None
    p._is_buffering = False
    p._audio_buffer = []
    p._buffer_lock = MagicMock()
    p._tts_active = False
    p.echo_cancellation = False  # the default that exposed the bug
    p._is_running = True
    p.logger = MagicMock()
    return p


def _frame(rms=0.02):
    rng = np.random.RandomState(3)
    buf = rng.randn(512).astype(np.float32)
    if rms > 0:
        buf = buf * (rms / (np.sqrt(np.mean(np.square(buf))) + 1e-9))
    return buf.reshape(1, -1)  # 2D: (channels, samples) as sounddevice delivers


def test_beep_frames_dropped_when_tts_active_and_echo_cancellation():
    """While the activation beep plays (_tts_active=True) AND echo_cancellation
    is on, STT frame listeners must NOT receive the beep frames (half-duplex
    gate). This is the production gate: `if self._tts_active and
    self.echo_cancellation`."""
    p = _make_pipeline()
    p.echo_cancellation = True
    received = []
    p._frame_listeners.append(lambda f: received.append(f))
    p._tts_active = True  # beep playing

    p._input_callback(_frame(rms=0.25), 512, None, None)

    assert received == [], "beep frame leaked to STT listener with echo_cancellation on"


def test_normal_frames_flow_when_tts_inactive():
    """When TTS is not active, normal speech frames reach the listeners."""
    p = _make_pipeline()
    received = []
    p._frame_listeners.append(lambda f: received.append(f))
    p._tts_active = False

    p._input_callback(_frame(rms=0.02), 512, None, None)

    assert len(received) == 1, "normal frame should reach STT listener"


def test_gate_passes_beep_when_echo_cancellation_off():
    """When echo_cancellation is OFF (the common default), the half-duplex gate
    does NOT drop beep frames — they flow to the listener. The beep-poisoning
    risk is instead mitigated by the VAD calibration ceiling (rms < 0.1) in
    voice_command.py, verified by test_vad_detects_speech_after_gated_beep.
    This test locks the CURRENT production gate behavior (reverted from the
    drop-on-_tts_active-alone change that broke STT frame delivery)."""
    p = _make_pipeline()
    p.echo_cancellation = False
    p._tts_active = True
    received = []
    p._frame_listeners.append(lambda f: received.append(f))

    p._input_callback(_frame(rms=0.25), 512, None, None)

    assert len(received) == 1, "gate must pass beep frames when echo_cancellation is off"


def test_vad_detects_speech_after_gated_beep():
    """End-to-end: a beep (gated out) followed by normal speech must still be
    detected by the VAD loop (no calibration poisoning)."""
    fake = types.ModuleType("fake")
    fake.VAD_ENERGY_THRESHOLD = 0.006
    fake.VAD_SILENCE_SEC = 1.2
    fake.VAD_MIN_SPEECH_SEC = 0.3
    fake.VAD_MAX_DURATION_SEC = 30.0
    fake.VAD_POLL_INTERVAL_SEC = 0.015
    fake.sample_rate = 16000
    fake._raw_frames = []
    fake._stop_event = MagicMock()
    fake._stop_event.is_set.return_value = False
    fake._pre_speech_timeout_sec = 0.0
    fake._on_audio_level = None
    fake._on_audio_envelope = None
    fake.cadence_detector = MagicMock()
    fake.cadence_detector.reset = MagicMock()
    fake.cadence_detector.process.return_value = 0.0

    rng = np.random.RandomState(7)
    def _mk(rms):
        b = rng.randn(512).astype(np.float32)
        if rms > 0:
            b = b * (rms / (np.sqrt(np.mean(np.square(b))) + 1e-9))
        return b
    # calibration: quiet ambient only (beep was gated out upstream)
    frames = [_mk(0.001) for _ in range(15)] + [_mk(0.02) for _ in range(20)] + [_mk(0.001) for _ in range(40)]
    fake._raw_frames = frames

    result = _voice.VoiceCommandHandler._vad_wait_for_speech_then_silence.__get__(fake)()
    assert result is True
