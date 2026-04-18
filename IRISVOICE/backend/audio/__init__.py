"""
IRIS Audio Module
Wake word detection, audio I/O, and voice command processing.
"""

from .engine import AudioEngine, VoiceState, get_audio_engine
from .pipeline import AudioPipeline

__all__ = [
    "AudioEngine",
    "VoiceState",
    "get_audio_engine",
    "AudioPipeline",
]
