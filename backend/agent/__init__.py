"""
IRIS Agent Module
Personality engine, TTS integration, conversation memory, and omni-conversation
"""

from .personality import PersonalityEngine, get_personality_engine
from .tts import TTSManager, get_tts_manager
from .memory import ConversationMemory, get_conversation_memory
from .conversation import AIConversationManager, get_conversation_manager
from .omni_conversation import OmniConversationManager, get_omni_conversation_manager
from .wake_config import WakeConfig, get_wake_config

__all__ = [
    "PersonalityEngine",
    "get_personality_engine",
    "TTSManager",
    "get_tts_manager",
    "ConversationMemory",
    "get_conversation_memory",
    "AIConversationManager",
    "get_conversation_manager",
    "OmniConversationManager",
    "get_omni_conversation_manager",
    "WakeConfig",
    "get_wake_config",
]
