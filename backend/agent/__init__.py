"""
IRIS Agent Module
Personality engine, TTS integration, conversation memory, and agent kernel
"""

from .personality import PersonalityEngine, get_personality_engine
from .tts import TTSManager, get_tts_manager
from .memory import ConversationMemory, get_conversation_memory, TaskRecord
from .lfm_audio_manager import LFMAudioManager, get_lfm_audio_manager
from .wake_config import WakeConfig, get_wake_config
from .agent_kernel import AgentKernel, get_agent_kernel
from .model_conversation import ModelConversation

__all__ = [
    "PersonalityEngine",
    "get_personality_engine",
    "TTSManager",
    "get_tts_manager",
    "ConversationMemory",
    "get_conversation_memory",
    "TaskRecord",
    "LFMAudioManager",
    "get_lfm_audio_manager",
    "WakeConfig",
    "get_wake_config",
    "AgentKernel",
    "get_agent_kernel",
    "ModelConversation",
]
