"""
Conversation Memory - Manages conversation history and context
"""
import json
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
import hashlib


@dataclass
class Message:
    """A single conversation message"""
    role: str  # "user" or "assistant"
    content: str
    timestamp: float
    audio_tokens: int = 0
    text_tokens: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        return cls(**data)


class ConversationMemory:
    """
    Manages conversation history with:
    - Token counting and context window management
    - Import/export functionality
    - Context visualization
    - Conversation search
    """
    
    _instance: Optional['ConversationMemory'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, max_context_tokens: int = 8192):
        if ConversationMemory._initialized:
            return
        
        self.max_context_tokens = max_context_tokens
        self.messages: List[Message] = []
        self.session_start = time.time()
        
        ConversationMemory._initialized = True
    
    def add_message(self, role: str, content: str, audio_tokens: int = 0, text_tokens: int = 0) -> None:
        """Add a message to conversation history"""
        message = Message(
            role=role,
            content=content,
            timestamp=time.time(),
            audio_tokens=audio_tokens,
            text_tokens=text_tokens
        )
        self.messages.append(message)
        
        # Prune old messages if context window exceeded
        self._prune_if_needed()
    
    def _prune_if_needed(self) -> None:
        """Remove oldest messages if token limit exceeded"""
        total_tokens = sum(m.text_tokens + m.audio_tokens for m in self.messages)
        
        while total_tokens > self.max_context_tokens and len(self.messages) > 2:
            # Remove oldest message (but keep at least 2)
            removed = self.messages.pop(0)
            total_tokens -= (removed.text_tokens + removed.audio_tokens)
            print(f"[ConversationMemory] Pruned old message, freed {removed.text_tokens + removed.audio_tokens} tokens")
    
    def get_context_window(self, max_messages: Optional[int] = None) -> List[Dict[str, str]]:
        """Get messages formatted for context window"""
        messages = self.messages
        if max_messages:
            messages = messages[-max_messages:]
        
        return [{"role": m.role, "content": m.content} for m in messages]
    
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
            "message_count": len(self.messages)
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
                    "timestamp": datetime.fromtimestamp(m.timestamp).isoformat()
                }
                for m in self.messages[-10:]  # Last 10 messages
            ]
        }
    
    def clear(self) -> None:
        """Clear all conversation history"""
        self.messages.clear()
        self.session_start = time.time()
        print("[ConversationMemory] Conversation cleared")
    
    def export_to_file(self, filepath: str) -> bool:
        """Export conversation to JSON file"""
        try:
            data = {
                "exported_at": datetime.now().isoformat(),
                "session_start": datetime.fromtimestamp(self.session_start).isoformat(),
                "messages": [m.to_dict() for m in self.messages]
            }
            
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            
            print(f"[ConversationMemory] Exported {len(self.messages)} messages to {filepath}")
            return True
            
        except Exception as e:
            print(f"[ConversationMemory] Export error: {e}")
            return False
    
    def import_from_file(self, filepath: str) -> bool:
        """Import conversation from JSON file"""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            self.messages = [Message.from_dict(m) for m in data.get("messages", [])]
            print(f"[ConversationMemory] Imported {len(self.messages)} messages from {filepath}")
            return True
            
        except Exception as e:
            print(f"[ConversationMemory] Import error: {e}")
            return False
    
    def search(self, query: str) -> List[Message]:
        """Search conversation history"""
        query_lower = query.lower()
        return [m for m in self.messages if query_lower in m.content.lower()]
    
    def get_summary(self) -> str:
        """Get conversation summary"""
        token_info = self.get_token_count()
        duration = time.time() - self.session_start
        
        return f"""Conversation Summary:
- Messages: {token_info['message_count']}
- Duration: {duration / 60:.1f} minutes
- Tokens: {token_info['total_tokens']} / {token_info['max_tokens']} ({token_info['audio_tokens']} audio, {token_info['text_tokens']} text)
- Usage: {(token_info['total_tokens'] / token_info['max_tokens']) * 100:.1f}%"""


def get_conversation_memory() -> ConversationMemory:
    """Get the singleton ConversationMemory instance"""
    return ConversationMemory()
