"""
IRIS Agent Module
Personality engine, TTS integration, conversation memory, and omni-conversation
"""

from .personality import PersonalityEngine, get_personality_engine
from .tts import TTSManager, get_tts_manager
from .memory import ConversationMemory, get_conversation_memory, TaskRecord
from .conversation import AIConversationManager, get_conversation_manager
from .omni_conversation import OmniConversationManager, get_omni_conversation_manager
from .unified_conversation import UnifiedConversationManager, get_unified_conversation_manager
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
    "AIConversationManager",
    "get_conversation_manager",
    "OmniConversationManager",
    "get_omni_conversation_manager",
    "UnifiedConversationManager",
    "get_unified_conversation_manager",
    "LFMAudioManager",
    "get_lfm_audio_manager",
    "WakeConfig",
    "get_wake_config",
    "AgentKernel",
    "get_agent_kernel",
    "ModelConversation",
]
