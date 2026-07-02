"""
IRIS Audio Module
Wake word detection, audio I/O, voice command processing, and ASR.

Components:
  - AudioEngine         : sounddevice input loop, Porcupine wake word,
                          cadence detection, playback thread, barge-in
  - AudioPipeline       : half-duplex gate (TTS mutes mic capture)
  - VoiceCommandHandler : orchestrates voice commands from wake to dispatch
  - ParakeetService     : standalone ASR service (HuggingFace Parakeet TDT 0.6B v3)
                          serving both Tauri widget and web browser
  - ParakeetStreamingBuffer : cache-aware TDT chunked inference wrapper
"""

from .engine import AudioEngine, VoiceState, get_audio_engine
from .pipeline import AudioPipeline
from .parakeet_buffer import Hypothesis, ParakeetStreamingBuffer

# parakeet_service is heavy (FastAPI + HF + torch) and can hang during import.
# Never import at module level — use get_parakeet_service() instead.
_PARASERVICE: dict = {"loaded": False, "mod": None}


def get_parakeet_service():
    """Lazy accessor for parakeet_service (FastAPI app, SoTA ASR).

    torch import can hang indefinitely on some systems (CUDA init), so this
    is deferred until the first actual ASR request.  Returns None if unavailable.
    """
    if not _PARASERVICE["loaded"]:
        _PARASERVICE["loaded"] = True
        try:
            from . import parakeet_service as _m

            _PARASERVICE["mod"] = _m
        except Exception:
            pass
    return _PARASERVICE["mod"]


__all__ = [
    "AudioEngine",
    "VoiceState",
    "get_audio_engine",
    "AudioPipeline",
    "Hypothesis",
    "ParakeetStreamingBuffer",
    "get_parakeet_service",
]
