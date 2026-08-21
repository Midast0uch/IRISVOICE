"""
Tests for adaptive VAD in backend/audio/voice_command.py (_vad_wait_for_speech_then_silence).

Verifies plan §1.3 contracts:
  - adaptive threshold calibrates from ambient noise (quiet vs noisy room)
  - silence detection triggers STT after adaptive frames
  - max listening timeout forces STT when speech started
  - <0.3s speech bursts are discarded as noise
"""
import sys
import types
import importlib.util
import logging
from unittest.mock import MagicMock

import numpy as np
import pytest

# DEBT FIX (pin_fd5b312e69bf / c01534199cdb): this used to be a module-level
# `logging.disable(logging.CRITICAL)`, which is PROCESS-GLOBAL state — pytest
# imports every collected module regardless of -k, so importing this file
# silently killed ALL logging (and every caplog assertion) for the rest of the
# session. Now scoped: disabled only while this module's tests run, restored
# afterwards.
@pytest.fixture(autouse=True)
def _silence_vad_logs():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)

# Stub out heavy audio deps so we can import voice_command without loading
# sounddevice/torch (which hang or are slow on import in the test env).
# We load voice_command.py directly via importlib, bypassing the package
# __init__ (which imports the real engine). Relative imports resolve to stubs.
# We do NOT leave `backend` itself stubbed in sys.modules: voice_command.py
# only uses relative imports (from .engine / .cadence_detector), so the real
# package keeps its __path__ and backend.* stays resolvable for every other
# test file in the same session (mirrors test_vad_first_wake.py; avoids
# cross-test sys.modules pollution).
_orig_modules = {
    name: sys.modules.get(name) for name in (
        "backend",
        "backend.audio",
        "backend.audio.engine",
        "backend.audio.cadence_detector",
        "backend.audio.voice_command",
    )
}

_stub_audio = types.ModuleType("backend.audio")
_stub_audio.__path__ = []
sys.modules["backend.audio"] = _stub_audio

_stub_engine = types.ModuleType("backend.audio.engine")
_stub_engine.AudioEngine = object
_stub_engine.VoiceState = object
_stub_engine.get_audio_engine = lambda *a, **k: None
sys.modules["backend.audio.engine"] = _stub_engine

_stub_cad = types.ModuleType("backend.audio.cadence_detector")
_stub_cad.CadenceDetector = object
sys.modules["backend.audio.cadence_detector"] = _stub_cad

_spec = importlib.util.spec_from_file_location(
    "backend.audio.voice_command", "backend/audio/voice_command.py"
)
_voice_mod = importlib.util.module_from_spec(_spec)
sys.modules["backend.audio.voice_command"] = _voice_mod
_spec.loader.exec_module(_voice_mod)
VoiceCommandHandler = _voice_mod.VoiceCommandHandler

# Restore the real package tree in sys.modules. The VAD method was already
# bound above (VoiceCommandHandler is captured, not re-looked-up at runtime),
# so later test files can import the real backend.* names again.
for _name, _mod in _orig_modules.items():
    if _mod is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _mod


def _make_frames(rms_values):
    """Build raw audio frames (512 samples each) from target RMS values."""
    rng = np.random.RandomState(42)
    frames = []
    for rms in rms_values:
        buf = rng.randn(512).astype(np.float32)
        if rms > 0:
            scale = rms / (np.sqrt(np.mean(np.square(buf))) + 1e-9)
            buf = buf * scale
        else:
            buf = np.zeros(512, dtype=np.float32)
        frames.append(buf)
    return frames


class _FakeVoiceCommand:
    """Minimal stand-in exposing only what the VAD method reads/writes."""

    VAD_ENERGY_THRESHOLD = 0.006
    VAD_SILENCE_SEC = 1.2
    VAD_MIN_SPEECH_SEC = 0.3
    VAD_MAX_DURATION_SEC = 30.0
    VAD_POLL_INTERVAL_SEC = 0.015
    sample_rate = 16000

    def __init__(self):
        self._raw_frames = []
        self._stop_event = MagicMock()
        self._stop_event.is_set.return_value = False
        self._pre_speech_timeout_sec = 0.0
        self._on_audio_level = None
        self._on_audio_envelope = None
        self.cadence_detector = MagicMock()
        self.cadence_detector.reset = MagicMock()
        self.cadence_detector.process.return_value = 0.0


def _bind_vad(fake):
    return types.MethodType(VoiceCommandHandler._vad_wait_for_speech_then_silence, fake)


def _run(fake, rms_values, max_duration_sec=30.0):
    # Pad with silence so the VAD loop always reaches max_frames and terminates.
    # In production frames arrive live; in tests we pre-load a fixed buffer, so
    # without padding the loop would wait forever for frames that never come.
    frame_sec = 512 / 16000
    max_frames = int(max_duration_sec / frame_sec) + 5
    padded = list(rms_values) + [0.001] * max(0, max_frames - len(rms_values))
    fake._raw_frames = _make_frames(padded)
    fake.VAD_MAX_DURATION_SEC = max_duration_sec
    return _bind_vad(fake)()


# frame_sec ≈ 0.032 s at 16 kHz
def test_adaptive_threshold_quiet_room_detects_soft_speech():
    """Quiet room: low noise floor → low threshold → soft speech (RMS 0.005) detected."""
    fake = _FakeVoiceCommand()
    # 15 ambient frames (quiet, RMS 0.001), 20 speech frames (RMS 0.005), 40 silence
    rms = [0.001] * 15 + [0.005] * 20 + [0.001] * 40
    result = _run(fake, rms)
    assert result is True


def test_adaptive_threshold_noisy_room_rejects_soft_speech():
    """Noisy room: high noise floor → high threshold → same soft speech (RMS 0.005) ignored."""
    fake = _FakeVoiceCommand()
    # 15 ambient frames (noisy, RMS 0.01), 20 speech frames (RMS 0.005), 40 silence
    rms = [0.01] * 15 + [0.005] * 20 + [0.001] * 40
    result = _run(fake, rms)
    assert result is False  # speech below noisy-room threshold → treated as noise


def test_silence_triggers_stt_after_adaptive_frames():
    """Speech followed by sustained silence → end-of-speech → STT triggered."""
    fake = _FakeVoiceCommand()
    rms = [0.001] * 15 + [0.02] * 20 + [0.001] * 40
    result = _run(fake, rms)
    assert result is True


def test_max_listening_timeout_forces_stt_when_speech_started():
    """Hard cap: if speech started but never ends, loop ends → STT forced (True)."""
    fake = _FakeVoiceCommand()
    # Short max duration; speech only, no silence → hits cap with speech_started=True
    rms = [0.001] * 15 + [0.02] * 200
    result = _run(fake, rms, max_duration_sec=2.0)
    assert result is True


def test_max_listening_timeout_skips_when_no_speech():
    """Hard cap: only silence captured → loop ends → STT skipped (False)."""
    fake = _FakeVoiceCommand()
    rms = [0.001] * 200  # silence only
    result = _run(fake, rms, max_duration_sec=2.0)
    assert result is False


def test_short_speech_burst_discarded():
    """<0.3s speech burst (5 frames) is below VAD_MIN_SPEECH_SEC → discarded (False)."""
    fake = _FakeVoiceCommand()
    # 15 ambient, 5 speech frames (<0.3s), then long silence → pre-speech timeout
    rms = [0.001] * 15 + [0.02] * 5 + [0.001] * 200
    result = _run(fake, rms, max_duration_sec=2.0)
    assert result is False


def test_no_speech_returns_false():
    """Pure ambient noise, no speech onset → False (avoid hallucination)."""
    fake = _FakeVoiceCommand()
    rms = [0.001] * 200
    result = _run(fake, rms, max_duration_sec=2.0)
    assert result is False
