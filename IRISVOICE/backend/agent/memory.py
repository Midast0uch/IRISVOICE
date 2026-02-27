"""
Conversation Memory - Manages conversation history and context
"""
import logging
import json
import time
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
import hashlib

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """A single conversation message"""
    role: str  # "user" or "assistant"
    content: str
    timestamp: float
    audio_tokens: int = 0
    text_tokens: int = 0
    tool_results: Optional[List[Dict[str, Any]]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        return cls(**data)


class ConversationMemory:
    """
    Manages conversation history with:
    - Configurable message limit (default 10)
    - Rolling window of recent messages
    - Persistence to session storage
    - Conversation archival on session end
    - Tool execution results in context
    """
    
    def __init__(
        self, 
        session_id: str,
        max_messages: int = 10,
        max_context_tokens: int = 8192,
        session_storage_path: Optional[str] = None
    ):
        """
        Initialize ConversationMemory for a session.
        
        Args:
            session_id: Unique session identifier
            max_messages: Maximum number of messages to keep (default 10)
            max_context_tokens: Maximum context window tokens (default 8192)
            session_storage_path: Path to session storage directory
        """
        self.session_id = session_id
        self.max_messages = max_messages
        self.max_context_tokens = max_context_tokens
        self.messages: List[Message] = []
        self.session_start = time.time()
        
        # Set up session storage path
        if session_storage_path is None:
            session_storage_path = os.path.join("backend", "sessions", session_id)
        self.session_storage_path = Path(session_storage_path)
        self.session_storage_path.mkdir(parents=True, exist_ok=True)
        
        # Load persisted conversation if exists
        self._load_from_session_storage()
    
    def add_message(
        self, 
        role: str, 
        content: str, 
        audio_tokens: int = 0, 
        text_tokens: int = 0,
        tool_results: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        """
        Add a message to conversation history.
        Maintains rolling window of max_messages most recent messages.
        
        Args:
            role: Message role ("user" or "assistant")
            content: Message content
            audio_tokens: Number of audio tokens
            text_tokens: Number of text tokens
            tool_results: Optional tool execution results to include in context
        """
        message = Message(
            role=role,
            content=content,
            timestamp=time.time(),
            audio_tokens=audio_tokens,
            text_tokens=text_tokens,
            tool_results=tool_results
        )
        self.messages.append(message)
        
        # Maintain rolling window of max_messages
        if len(self.messages) > self.max_messages:
            removed = self.messages.pop(0)
            logger.debug(
                f"[ConversationMemory] Removed oldest message from session {self.session_id}, "
                f"maintaining limit of {self.max_messages} messages"
            )
        
        # Persist to session storage
        self._persist_to_session_storage()
    
    def get_context(self, max_messages: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get conversation context formatted for LLM consumption.
        Includes both user/assistant messages and tool results.
        
        Args:
            max_messages: Optional limit on number of messages to return
            
        Returns:
            List of message dictionaries with role, content, and optional tool_results
        """
        messages = self.messages
        if max_messages:
            messages = messages[-max_messages:]
        
        context = []
        for m in messages:
            msg_dict = {"role": m.role, "content": m.content}
            if m.tool_results:
                msg_dict["tool_results"] = m.tool_results
            context.append(msg_dict)
        
        return context
    
    def clear(self) -> None:
        """
        Clear all conversation history for this session.
        Persists the cleared state to session storage.
        """
        self.messages.clear()
        self.session_start = time.time()
        self._persist_to_session_storage()
        logger.info(f"[ConversationMemory] Conversation cleared for session {self.session_id}")
    
    def _persist_to_session_storage(self) -> None:
        """Persist conversation history to session storage"""
        try:
            conversation_file = self.session_storage_path / "conversation.json"
            data = {
                "session_id": self.session_id,
                "session_start": self.session_start,
                "last_updated": time.time(),
                "max_messages": self.max_messages,
                "messages": [m.to_dict() for m in self.messages]
            }
            
            with open(conversation_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.debug(
                f"[ConversationMemory] Persisted {len(self.messages)} messages "
                f"to session storage for {self.session_id}"
            )
            
        except Exception as e:
            logger.error(
                f"[ConversationMemory] Failed to persist conversation for session {self.session_id}: {e}"
            )
    
    def _load_from_session_storage(self) -> None:
        """Load conversation history from session storage if exists"""
        try:
            conversation_file = self.session_storage_path / "conversation.json"
            if conversation_file.exists():
                with open(conversation_file, 'r') as f:
                    data = json.load(f)
                
                self.messages = [Message.from_dict(m) for m in data.get("messages", [])]
                self.session_start = data.get("session_start", time.time())
                
                logger.info(
                    f"[ConversationMemory] Loaded {len(self.messages)} messages "
                    f"from session storage for {self.session_id}"
                )
        except Exception as e:
            logger.warning(
                f"[ConversationMemory] Failed to load conversation for session {self.session_id}: {e}"
            )
    
    def archive_on_session_end(self) -> bool:
        """
        Archive conversation history when session ends.
        Creates a timestamped archive file in the session directory.
        
        Returns:
            True if archival succeeded, False otherwise
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_file = self.session_storage_path / f"conversation_archive_{timestamp}.json"
            
            data = {
                "session_id": self.session_id,
                "archived_at": datetime.now().isoformat(),
                "session_start": datetime.fromtimestamp(self.session_start).isoformat(),
                "session_duration_seconds": time.time() - self.session_start,
                "message_count": len(self.messages),
                "messages": [m.to_dict() for m in self.messages]
            }
            
            with open(archive_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.info(
                f"[ConversationMemory] Archived {len(self.messages)} messages "
                f"for session {self.session_id} to {archive_file}"
            )
            return True
            
        except Exception as e:
            logger.error(
                f"[ConversationMemory] Failed to archive conversation for session {self.session_id}: {e}"
            )
            return False
    
    def _prune_if_needed(self) -> None:
        """Remove oldest messages if token limit exceeded (legacy method for backward compatibility)"""
        total_tokens = sum(m.text_tokens + m.audio_tokens for m in self.messages)
        
        while total_tokens > self.max_context_tokens and len(self.messages) > 2:
            # Remove oldest message (but keep at least 2)
            removed = self.messages.pop(0)
            total_tokens -= (removed.text_tokens + removed.audio_tokens)
            logger.info(
                f"[ConversationMemory] Pruned old message, freed {removed.text_tokens + removed.audio_tokens} tokens"
            )
    
    def get_context_window(self, max_messages: Optional[int] = None) -> List[Dict[str, str]]:
        """
        Get messages formatted for context window (legacy method).
        Use get_context() for new code.
        """
        return self.get_context(max_messages=max_messages)
    
    def get_token_count(self) -> Dict[str, int]:
        """Get current token usage statistics"""
        audio_tokens = sum(m.audio_tokens for m in self.messages)
        text_tokens = sum(m.text_tokens for m in self.messages)
        
        return {
            "audio_tokens": audio_tokens,
            "text_tokens": text_tokens,
            "total_tokens": audio_tokens + text_tokens,
            "max_tokens": self.max_context_tokens,
            "available": self.max_context_tokens - (audio_tokens + text_tokens),
            "message_count": len(self.messages),
            "max_messages": self.max_messages
        }
    
    def get_context_visualization(self) -> Dict[str, Any]:
        """Get visualization data for context window"""
        token_info = self.get_token_count()
        
        return {
            "usage_percent": (token_info["total_tokens"] / token_info["max_tokens"]) * 100,
            "token_breakdown": {
                "audio": token_info["audio_tokens"],
                "text": token_info["text_tokens"],
                "available": token_info["available"]
            },
            "messages": [
                {
                    "role": m.role,
                    "preview": m.content[:50] + "..." if len(m.content) > 50 else m.content,
                    "tokens": m.text_tokens + m.audio_tokens,
                    "timestamp": datetime.fromtimestamp(m.timestamp).isoformat(),
                    "has_tool_results": m.tool_results is not None
                }
                for m in self.messages[-10:]  # Last 10 messages
            ]
        }
    
    def get_summary(self) -> str:
        """Get conversation summary"""
        token_info = self.get_token_count()
        duration = time.time() - self.session_start
        
        return f"""Conversation Summary (Session: {self.session_id}):
- Messages: {token_info['message_count']} / {token_info['max_messages']} (limit)
- Duration: {duration / 60:.1f} minutes
- Tokens: {token_info['total_tokens']} / {token_info['max_tokens']} ({token_info['audio_tokens']} audio, {token_info['text_tokens']} text)
- Usage: {(token_info['total_tokens'] / token_info['max_tokens']) * 100:.1f}%"""
    
    def export_to_file(self, filepath: str) -> bool:
        """Export conversation to JSON file"""
        try:
            data = {
                "session_id": self.session_id,
                "exported_at": datetime.now().isoformat(),
                "session_start": datetime.fromtimestamp(self.session_start).isoformat(),
                "max_messages": self.max_messages,
                "messages": [m.to_dict() for m in self.messages]
            }
            
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.info(f"[ConversationMemory] Exported {len(self.messages)} messages to {filepath}")
            return True
            
        except Exception as e:
            logger.error(f"[ConversationMemory] Export error: {e}")
            return False
    
    def import_from_file(self, filepath: str) -> bool:
        """Import conversation from JSON file"""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            self.messages = [Message.from_dict(m) for m in data.get("messages", [])]
            self._persist_to_session_storage()
            logger.info(f"[ConversationMemory] Imported {len(self.messages)} messages from {filepath}")
            return True
            
        except Exception as e:
            logger.error(f"[ConversationMemory] Import error: {e}")
            return False
    
    def search(self, query: str) -> List[Message]:
        """Search conversation history"""
        query_lower = query.lower()
        return [m for m in self.messages if query_lower in m.content.lower()]


# Legacy singleton support for backward compatibility
_legacy_instance: Optional[ConversationMemory] = None


def get_conversation_memory(
    session_id: str = "default",
    max_messages: int = 10,
    max_context_tokens: int = 8192
) -> ConversationMemory:
    """
    Get or create a ConversationMemory instance for a session.
    
    Args:
        session_id: Unique session identifier
        max_messages: Maximum number of messages to keep (default 10)
        max_context_tokens: Maximum context window tokens (default 8192)
        
    Returns:
        ConversationMemory instance for the session
    """
    # For backward compatibility, maintain a legacy singleton for "default" session
    global _legacy_instance
    if session_id == "default" and _legacy_instance is None:
        _legacy_instance = ConversationMemory(
            session_id=session_id,
            max_messages=max_messages,
            max_context_tokens=max_context_tokens
        )
        return _legacy_instance
    elif session_id == "default":
        return _legacy_instance
    
    # For non-default sessions, create new instances
    return ConversationMemory(
        session_id=session_id,
        max_messages=max_messages,
        max_context_tokens=max_context_tokens
    )
