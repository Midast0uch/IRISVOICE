"""
LFMAudioManager — Lightweight wake word configuration adapter.

Audio processing (LFM2-Audio) is handled by backend/audio/model_manager.py.
Porcupine detection is handled by backend/audio/engine.py.
This class now only holds wake phrase / TTS voice configuration state.

Previously loaded Whisper + SpeechT5 + LFM models (3 separate models).
All of that is now removed — ModelManager handles LFM2-Audio lazily on first voice command.
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class LFMAudioManager:
    """
    Lightweight configuration holder for voice/wake settings.
    Previously handled LFM model loading — now delegated to ModelManager.
    """
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.wake_phrase = self.config.get("wake_phrase", "jarvis")
        self.detection_sensitivity = self.config.get("detection_sensitivity", 50)
        self.tts_voice = self.config.get("tts_voice", "Nova")
        self.speaking_rate = self.config.get("speaking_rate", 1.0)
        self.is_initialized = True   # No longer needs heavy initialization
        self.callbacks = {}

    def set_callbacks(self, **kwargs):
        self.callbacks.update({k: v for k, v in kwargs.items() if v})

    def update_wake_config(self, wake_phrase=None, detection_sensitivity=None, activation_sound=None):
        if wake_phrase is not None:
            self.wake_phrase = wake_phrase
        if detection_sensitivity is not None:
            self.detection_sensitivity = detection_sensitivity

    def update_voice_config(self, tts_voice=None, speaking_rate=None):
        if tts_voice is not None:
            self.tts_voice = tts_voice
        if speaking_rate is not None:
            self.speaking_rate = speaking_rate

    async def initialize(self):
        """No-op — model loading delegated to ModelManager (lazy, on first voice command)."""
        logger.info("[LFMAudioManager] Lightweight config-only mode. LFM model loaded on first voice use.")

    async def cleanup(self):
        """No-op — nothing to clean up."""
        pass


_lfm_audio_manager_instance = None


def get_lfm_audio_manager() -> "LFMAudioManager":
    """Get the singleton LFMAudioManager (config-only)."""
    global _lfm_audio_manager_instance
    if _lfm_audio_manager_instance is None:
        _lfm_audio_manager_instance = LFMAudioManager({})
    return _lfm_audio_manager_instance
