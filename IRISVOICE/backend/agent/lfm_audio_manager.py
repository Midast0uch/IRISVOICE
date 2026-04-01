"""
LFMAudioManager — Lightweight wake word / voice configuration adapter.

Porcupine wake word detection  — backend/audio/engine.py
STT (speech-to-text)           — backend/audio/voice_command.py (faster-whisper)
TTS (text-to-speech)           — backend/agent/tts.py (CosyVoice3-0.5B)

This class only holds wake phrase / TTS voice configuration state.
It does not load any models.
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
        self.tts_voice = self.config.get("tts_voice", "Cloned Voice")
        self.speaking_rate = self.config.get("speaking_rate", 1.0)
        self.is_initialized = True   # config-only, no model loading
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
        """No-op — this class is config-only. TTS/STT models load in tts.py / voice_command.py."""
        logger.info("[LFMAudioManager] Config-only mode — no models to load here.")

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
