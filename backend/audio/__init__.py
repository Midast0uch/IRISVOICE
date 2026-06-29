"""
IRIS Audio Module
Wake word detection, audio I/O, voice command processing, and ASR.

Components:
  - AudioEngine         : sounddevice input loop, Porcupine wake word,
                          cadence detection, playback thread, barge-in
  - AudioPipeline       : half-duplex gate (TTS mutes mic capture)
  - VoiceCommandHandler : orchestrates voice commands from wake to dispatch
  - ParakeetService     : standalone ASR service (NeMo TDT 0.6B v3)
                          serving both Tauri widget and web browser
  - ParakeetStreamingBuffer : cache-aware TDT chunked inference wrapper
"""

from .engine import AudioEngine, VoiceState, get_audio_engine
from .pipeline import AudioPipeline
from .parakeet_buffer import Hypothesis, ParakeetStreamingBuffer

# parakeet_service is heavy (FastAPI + NeMo) — import lazily
try:
    from .parakeet_service import ServiceConfig, ServiceMetrics, create_app
    _PARAKEET_AVAILABLE = True
except ImportError:
    _PARAKEET_AVAILABLE = False

__all__ = [
    "AudioEngine",
    "VoiceState",
    "get_audio_engine",
    "AudioPipeline",
    "Hypothesis",
    "ParakeetStreamingBuffer",
    "ServiceConfig",
    "ServiceMetrics",
    "create_app",
    "_PARAKEET_AVAILABLE",
]
