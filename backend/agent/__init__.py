"""
IRIS Agent Module
Personality engine, TTS integration, and conversation memory
"""

from .personality import PersonalityEngine, get_personality_engine
from .tts import TTSManager, get_tts_manager
from .memory import ConversationMemory, get_conversation_memory
from .wake_config import WakeConfig, get_wake_config

__all__ = [
    "PersonalityEngine",
    "get_personality_engine",
    "TTSManager",
    "get_tts_manager",
    "ConversationMemory",
    "get_conversation_memory",
    "WakeConfig",
    "get_wake_config",
]
