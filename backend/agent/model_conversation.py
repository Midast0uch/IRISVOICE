#!/usr/bin/env python3
"""
Model Conversation

This module provides a class to manage the conversation history between models.
"""

from typing import List, Dict, Any

class ModelConversation:
    """Manages the conversation history between the brain and executor models."""

    def __init__(self):
        self.history: List[Dict[str, Any]] = []

    def add_message(self, role: str, content: Any):
        """Adds a message to the conversation history."""
        self.history.append({"role": role, "content": content})

    def get_history(self) -> List[Dict[str, Any]]:
        """Returns the conversation history."""
        return self.history

    def clear_history(self):
        """Clears the conversation history."""
        self.history = []
