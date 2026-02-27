"""
Property-based tests for clear chat action.

Feature: irisvoice-backend-integration
Property 16: Clear Chat Action

For any clear_chat message, the Agent_Kernel shall clear the conversation history
and subsequent messages shall have no prior context.

Validates: Requirements 17.3
"""

import pytest
from hypothesis import given, strategies as st, settings
from unittest.mock import Mock, AsyncMock, patch
import sys
import os
import tempfile
import shutil

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.agent.memory import ConversationMemory


# Test data generators
@st.composite
def conversation_histories(draw):
    """Generate conversation histories with varying lengths."""
    num_messages = draw(st.integers(min_value=1, max_value=20))
    messages = []
    for _ in range(num_messages):
        role = draw(st.sampled_from(["user", "assistant"]))
        content = draw(st.text(min_size=1, max_size=200))
        messages.append({"role": role, "content": content})
    return messages


@st.composite
def session_ids(draw):
    """Generate valid session IDs."""
    return draw(st.uuids()).hex


# Property 16: Clear Chat Action
@given(
    initial_history=conversation_histories(),
    session_id=session_ids(),
    new_message=st.text(min_size=1, max_size=100)
)
@settings(max_examples=100, deadline=None)
@pytest.mark.asyncio
async def test_clear_chat_removes_all_context(initial_history, session_id, new_message):
    """
    Property 16: Clear Chat Action
    
    For any clear_chat message, the Agent_Kernel shall clear the conversation history
    and subsequent messages shall have no prior context.
    
    Validates: Requirements 17.3
    """
    # Create temporary directory for this test
    temp_dir = tempfile.mkdtemp()
    try:
        # Create conversation memory with temp storage
        memory = ConversationMemory(
            session_id=session_id, 
            max_messages=50,
            session_storage_path=temp_dir
        )
        
        # Add initial conversation history
        for msg in initial_history:
            memory.add_message(msg["role"], msg["content"])
        
        # Verify history exists
        context_before = memory.get_context()
        assert len(context_before) == len(initial_history), \
            "Initial history should be stored"
        
        # Clear chat
        memory.clear()
        
        # Verify history is cleared
        context_after_clear = memory.get_context()
        assert len(context_after_clear) == 0, \
            "Conversation history should be empty after clear"
        
        # Add a new message
        memory.add_message("user", new_message)
        
        # Verify new message has no prior context
        context_after_new = memory.get_context()
        assert len(context_after_new) == 1, \
            "Only the new message should be in context"
        assert context_after_new[0]["role"] == "user", \
            "New message should be from user"
        assert context_after_new[0]["content"] == new_message, \
            "New message content should match"
    finally:
        # Clean up temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)


@given(
    num_clears=st.integers(min_value=1, max_value=5),
    session_id=session_ids()
)
@settings(max_examples=100, deadline=None)
@pytest.mark.asyncio
async def test_clear_chat_idempotent(num_clears, session_id):
    """
    Property: Clear chat is idempotent
    
    Clearing chat multiple times should have the same effect as clearing once.
    """
    # Create temporary directory for this test
    temp_dir = tempfile.mkdtemp()
    try:
        # Create conversation memory with some messages
        memory = ConversationMemory(
            session_id=session_id, 
            max_messages=50,
            session_storage_path=temp_dir
        )
        memory.add_message("user", "Hello")
        memory.add_message("assistant", "Hi there")
        
        # Clear multiple times
        for _ in range(num_clears):
            memory.clear()
        
        # Verify history is still empty
        context = memory.get_context()
        assert len(context) == 0, \
            "Multiple clears should result in empty history"
    finally:
        # Clean up temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)


@given(
    messages_before=conversation_histories(),
    messages_after=conversation_histories(),
    session_id=session_ids()
)
@settings(max_examples=100, deadline=None)
@pytest.mark.asyncio
async def test_clear_chat_complete_reset(messages_before, messages_after, session_id):
    """
    Property: Clear chat provides complete reset
    
    After clearing, the conversation should behave as if it's a fresh start.
    """
    # Create temporary directory for this test
    temp_dir = tempfile.mkdtemp()
    try:
        # Create conversation memory
        memory = ConversationMemory(
            session_id=session_id, 
            max_messages=50,
            session_storage_path=temp_dir
        )
        
        # Add messages before clear
        for msg in messages_before:
            memory.add_message(msg["role"], msg["content"])
        
        # Clear
        memory.clear()
        
        # Add messages after clear
        for msg in messages_after:
            memory.add_message(msg["role"], msg["content"])
        
        # Verify only post-clear messages are in context
        context = memory.get_context()
        assert len(context) == len(messages_after), \
            "Only post-clear messages should be in context"
        
        # Verify content matches post-clear messages
        for i, msg in enumerate(messages_after):
            assert context[i]["role"] == msg["role"], \
                f"Message {i} role should match post-clear message"
            assert context[i]["content"] == msg["content"], \
                f"Message {i} content should match post-clear message"
    finally:
        # Clean up temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
