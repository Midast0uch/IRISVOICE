"""
Property-based tests for conversation context maintenance.
Tests universal properties that should hold for conversation history management.
"""
import pytest
from hypothesis import given, settings, strategies as st, seed
import sys
import os
import tempfile
import shutil
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from backend.agent.memory import ConversationMemory, Message


# ============================================================================
# Test Data Generators (Hypothesis Strategies)
# ============================================================================

@st.composite
def message_content(draw):
    """Generate realistic message content."""
    return draw(st.one_of(
        # Simple messages
        st.text(min_size=1, max_size=500),
        # Questions
        st.sampled_from([
            "What is the weather today?",
            "Can you help me with this task?",
            "How do I solve this problem?",
            "Tell me about artificial intelligence",
            "What are the best practices for coding?",
        ]),
        # Commands
        st.sampled_from([
            "Search for information about Python",
            "Open the browser",
            "Create a new file",
            "Run the tests",
            "Deploy the application",
        ])
    ))


@st.composite
def message_role(draw):
    """Generate message roles."""
    return draw(st.sampled_from(["user", "assistant"]))


@st.composite
def tool_results(draw):
    """Generate tool execution results."""
    num_results = draw(st.integers(min_value=1, max_value=5))
    results = []
    for _ in range(num_results):
        result = {
            "tool": draw(st.sampled_from([
                "web_search", "file_manager", "browser", 
                "system", "app_launcher", "vision"
            ])),
            "result": draw(st.text(min_size=1, max_size=200)),
            "success": draw(st.booleans())
        }
        results.append(result)
    return results


@st.composite
def conversation_sequence(draw):
    """Generate a sequence of conversation messages."""
    num_messages = draw(st.integers(min_value=1, max_value=20))
    messages = []
    for _ in range(num_messages):
        role = draw(message_role())
        content = draw(message_content())
        text_tokens = draw(st.integers(min_value=1, max_value=100))
        
        # Randomly include tool results for assistant messages
        include_tools = draw(st.booleans()) if role == "assistant" else False
        tool_res = draw(tool_results()) if include_tools else None
        
        messages.append({
            "role": role,
            "content": content,
            "text_tokens": text_tokens,
            "tool_results": tool_res
        })
    return messages


# ============================================================================
# Property 14: Conversation Context Maintenance
# Feature: irisvoice-backend-integration, Property 14: Conversation Context Maintenance
# Validates: Requirements 5.5, 17.1, 17.4, 17.5
# ============================================================================

class TestConversationContextMaintenance:
    """
    Property 14: Conversation Context Maintenance
    
    For any sequence of messages in a session, the Agent_Kernel shall maintain 
    conversation history and include previous messages in the context for 
    subsequent responses.
    """
    
    @settings(max_examples=10, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        messages=conversation_sequence()
    )
    def test_conversation_history_maintained_across_messages(self, messages):
        """
        Property: For any sequence of messages, the conversation history 
        maintains all messages in order.
        
        # Feature: irisvoice-backend-integration, Property 14: Conversation Context Maintenance
        **Validates: Requirements 5.5, 17.1**
        """
        # Setup
        temp_session_dir = tempfile.mkdtemp()
        try:
            memory = ConversationMemory(
                session_id="test-session",
                max_messages=100,  # Large enough to hold all messages
                session_storage_path=temp_session_dir
            )
            
            # Execute: Add all messages to conversation
            for msg in messages:
                memory.add_message(
                    role=msg["role"],
                    content=msg["content"],
                    text_tokens=msg["text_tokens"],
                    tool_results=msg["tool_results"]
                )
            
            # Verify: All messages are maintained in order
            context = memory.get_context()
            
            assert len(context) == len(messages), f"Context should contain all {len(messages)} messages"
            
            # Verify message ordering
            for i, (ctx_msg, orig_msg) in enumerate(zip(context, messages)):
                assert ctx_msg["role"] == orig_msg["role"], f"Message {i}: role mismatch"
                assert ctx_msg["content"] == orig_msg["content"], f"Message {i}: content mismatch"
                
                # Verify tool results are included if present
                if orig_msg["tool_results"]:
                    assert "tool_results" in ctx_msg, f"Message {i}: tool_results should be included in context"
                    assert ctx_msg["tool_results"] == orig_msg["tool_results"], f"Message {i}: tool_results mismatch"
        finally:
            shutil.rmtree(temp_session_dir, ignore_errors=True)
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        messages=conversation_sequence(),
        max_messages=st.integers(min_value=2, max_value=10)
    )
    def test_conversation_respects_message_limit(self, messages, max_messages):
        """
        Property: For any sequence of messages with a configured limit, 
        the conversation maintains only the most recent N messages.
        
        # Feature: irisvoice-backend-integration, Property 14: Conversation Context Maintenance
        **Validates: Requirements 17.1, 17.4**
        """
        # Setup
        temp_session_dir = tempfile.mkdtemp()
        try:
            memory = ConversationMemory(
                session_id="test-session",
                max_messages=max_messages,
                session_storage_path=temp_session_dir
            )
            
            # Execute: Add all messages
            for msg in messages:
                memory.add_message(
                    role=msg["role"],
                    content=msg["content"],
                    text_tokens=msg["text_tokens"],
                    tool_results=msg["tool_results"]
                )
            
            # Verify: Only most recent max_messages are kept
            context = memory.get_context()
            
            expected_count = min(len(messages), max_messages)
            assert len(context) == expected_count, f"Context should contain at most {max_messages} messages"
            
            # Verify we have the most recent messages
            if len(messages) > max_messages:
                # Should have the last max_messages messages
                expected_messages = messages[-max_messages:]
                for i, (ctx_msg, orig_msg) in enumerate(zip(context, expected_messages)):
                    assert ctx_msg["content"] == orig_msg["content"], "Should maintain most recent messages in order"
        finally:
            shutil.rmtree(temp_session_dir, ignore_errors=True)
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        messages=conversation_sequence()
    )
    def test_tool_results_included_in_context(self, messages):
        """
        Property: For any message with tool results, the tool results 
        are included in the conversation context.
        
        # Feature: irisvoice-backend-integration, Property 14: Conversation Context Maintenance
        **Validates: Requirements 17.4, 17.5**
        """
        # Setup
        temp_session_dir = tempfile.mkdtemp()
        try:
            memory = ConversationMemory(
                session_id="test-session",
                max_messages=100,
                session_storage_path=temp_session_dir
            )
            
            # Execute: Add messages
            for msg in messages:
                memory.add_message(
                    role=msg["role"],
                    content=msg["content"],
                    text_tokens=msg["text_tokens"],
                    tool_results=msg["tool_results"]
                )
            
            # Verify: Tool results are included in context
            context = memory.get_context()
            
            for i, (ctx_msg, orig_msg) in enumerate(zip(context, messages)):
                if orig_msg["tool_results"] is not None:
                    assert "tool_results" in ctx_msg, f"Message {i} with tool results should include them in context"
                    assert ctx_msg["tool_results"] == orig_msg["tool_results"], f"Message {i} tool results should match original"
                else:
                    # Tool results key may or may not be present if None
                    if "tool_results" in ctx_msg:
                        assert ctx_msg["tool_results"] is None, f"Message {i} without tool results should have None or no key"
        finally:
            shutil.rmtree(temp_session_dir, ignore_errors=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
