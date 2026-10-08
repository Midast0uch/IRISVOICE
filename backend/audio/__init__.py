"""
IRIS Audio Module
Wake word detection, audio I/O, voice command processing, and ASR.

Components:
  - AudioEngine         : sounddevice input loop, Porcupine wake word,
                          cadence detection, playback thread, barge-in
  - AudioPipeline       : half-duplex gate (TTS mutes mic capture)
  - VoiceCommandHandler : orchestrates voice commands from wake to dispatch
  - Phonon-2            : live streaming STT on CPU (fermion server,
                          backend/audio/phonon2_stream.py) — replaced the
                          retired Parakeet ASR (2026-10-08,
                          specs/phonon2-d1-model-swap)
"""

from .engine import AudioEngine, VoiceState, get_audio_engine
from .pipeline import AudioPipeline

__all__ = [
    "AudioEngine",
    "VoiceState",
    "get_audio_engine",
    "AudioPipeline",
]
