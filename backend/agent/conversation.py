"""AI Conversation manager for LM Studio"""
import os
from typing import Dict, List, Optional, Any

import requests

from .personality import get_personality_engine
from .memory import get_conversation_memory


class AIConversationManager:
    """Handles conversation flow via LM Studio (OpenAI-compatible API)."""

    DEFAULT_ENDPOINT = "http://192.168.0.32:1234/v1/chat/completions"

    def __init__(self):
        self.config: Dict[str, Any] = {
            "endpoint": os.getenv("LM_STUDIO_ENDPOINT", self.DEFAULT_ENDPOINT),
            "model": os.getenv("LM_STUDIO_MODEL", "default"),
            "timeout": 60,
            "max_context_messages": 10,
            "temperature": 0.7,
        }

        self.personality = get_personality_engine()
        self.memory = get_conversation_memory()

    def update_config(self, **kwargs):
        # If endpoint is provided without /v1/chat/completions, append it
        if "endpoint" in kwargs and kwargs["endpoint"]:
            endpoint = kwargs["endpoint"]
            if not endpoint.endswith("/v1/chat/completions") and not endpoint.endswith("/v1/completions"):
                if endpoint.endswith("/"):
                    kwargs["endpoint"] = f"{endpoint}v1/chat/completions"
                else:
                    kwargs["endpoint"] = f"{endpoint}/v1/chat/completions"
        
        self.config.update({k: v for k, v in kwargs.items() if v is not None})

    def _build_messages(self, user_text: str) -> List[Dict[str, str]]:
        system_prompt = self.personality.get_system_prompt()
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt}
        ]

        history = self.memory.get_context_window(self.config.get("max_context_messages"))
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})
        return messages

    def generate_response(self, user_text: str) -> Optional[str]:
        if not user_text:
            return None

        messages = self._build_messages(user_text)
        payload = {
            "model": self.config["model"],
            "messages": messages,
            "temperature": self.config.get("temperature", 0.7),
        }

        endpoint = self.config.get("endpoint", self.DEFAULT_ENDPOINT)
        headers = {"Content-Type": "application/json"}

        try:
            response = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=self.config.get("timeout", 60),
            )
            response.raise_for_status()
            data = response.json()
            text = data["choices"][0]["message"]["content"].strip()

            self.memory.add_message("user", user_text, text_tokens=len(user_text))
            self.memory.add_message("assistant", text, text_tokens=len(text))

            return text
        except Exception as e:
            print(f"[AIConversationManager] Chat request failed: {e}")
            return None


_conversation_manager: Optional[AIConversationManager] = None


def get_conversation_manager() -> AIConversationManager:
    global _conversation_manager
    if _conversation_manager is None:
        _conversation_manager = AIConversationManager()
    return _conversation_manager
