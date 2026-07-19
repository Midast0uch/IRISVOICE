"""
IRIS Agent Module
Personality engine, TTS integration, conversation memory, and agent kernel
"""

from .personality import PersonalityEngine, get_personality_engine
from .tts import TTSManager, get_tts_manager
from .memory import ConversationMemory, get_conversation_memory, TaskRecord
from .wake_config import WakeConfig, get_wake_config
from .agent_kernel import (
    AgentKernel,
    get_agent_kernel,
    get_active_kernel,
    set_active_conversation,
)
from .model_conversation import ModelConversation

__all__ = [
    "PersonalityEngine",
    "get_personality_engine",
    "TTSManager",
    "get_tts_manager",
    "ConversationMemory",
    "get_conversation_memory",
    "TaskRecord",
    "WakeConfig",
    "get_wake_config",
    "AgentKernel",
    "get_agent_kernel",
    "get_active_kernel",
    "set_active_conversation",
    "ModelConversation",
]
