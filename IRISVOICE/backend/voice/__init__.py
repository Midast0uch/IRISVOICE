"""
IRIS Backend Voice Module

This module contains voice processing components:
- Audio engine
- Voice pipeline
- Wake word detection
- Voice activity detection (VAD)
- Voice command handling
"""

__all__ = [
    'get_audio_engine',
    'AudioPipeline',
    'VoiceCommandHandler',
    'VoiceState'
]

# Re-export audio components from their original locations
from backend.audio import get_audio_engine
from backend.audio.pipeline import AudioPipeline
from backend.audio.voice_command import VoiceCommandHandler, VoiceState
