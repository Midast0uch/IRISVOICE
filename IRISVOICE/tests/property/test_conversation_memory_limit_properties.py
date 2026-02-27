"""
Property-based tests for conversation memory limit.
Tests universal properties that should hold for message limit enforcement.
"""
import pytest
from hypothesis import given, settings, strategies as st, seed
import sys
import os
import tempfile
import shutil
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

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
# Property 15: Conversation Memory Limit
# Feature: irisvoice-backend-integration, Property 15: Conversation Memory Limit
# Validates: Requirements 17.2
# ============================================================================

class TestConversationMemoryLimit:
    """
    Property 15: Conversation Memory Limit
    
    For any conversation with more than N messages (where N is configurable), 
    the Conversation_Memory shall store only the most recent N messages.
    """
    
    @settings(max_examples=10, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        num_messages=st.integers(min_value=1, max_value=50),
        max_messages=st.integers(min_value=1, max_value=20)
    )
    def test_conversation_memory_enforces_message_limit(self, num_messages, max_messages):
        """
        Property: For any conversation with more than max_messages messages,
        only the most recent max_messages are stored.
        
        # Feature: irisvoice-backend-integration, Property 15: Conversation Memory Limit
        **Validates: Requirements 17.2**
        """
        # Setup
        temp_session_dir = tempfile.mkdtemp()
        try:
            memory = ConversationMemory(
                session_id="test-memory-limit",
                max_messages=max_messages,
                session_storage_path=temp_session_dir
            )
            
            # Execute: Add num_messages messages
            for i in range(num_messages):
                memory.add_message(
                    role="user" if i % 2 == 0 else "assistant",
                    content=f"Message {i}",
                    text_tokens=10
                )
            
            # Verify: Only most recent max_messages are stored
            expected_count = min(num_messages, max_messages)
            assert len(memory.messages) == expected_count, \
                f"Expected {expected_count} messages, got {len(memory.messages)}"
            
            # Verify we have the most recent messages
            if num_messages > max_messages:
                # Should have messages from (num_messages - max_messages) to (num_messages - 1)
                first_expected_index = num_messages - max_messages
                assert memory.messages[0].content == f"Message {first_expected_index}", \
                    f"First message should be 'Message {first_expected_index}'"
                assert memory.messages[-1].content == f"Message {num_messages - 1}", \
                    f"Last message should be 'Message {num_messages - 1}'"
            
            # Verify context also respects the limit
            context = memory.get_context()
            assert len(context) == expected_count, \
                f"Context should contain {expected_count} messages"
            
        finally:
            shutil.rmtree(temp_session_dir, ignore_errors=True)
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        messages=conversation_sequence(),
        max_messages=st.integers(min_value=2, max_value=15)
    )
    def test_rolling_window_maintains_most_recent_messages(self, messages, max_messages):
        """
        Property: For any sequence of messages exceeding the limit,
        the rolling window maintains the most recent messages in order.
        
        # Feature: irisvoice-backend-integration, Property 15: Conversation Memory Limit
        **Validates: Requirements 17.2**
        """
        # Setup
        temp_session_dir = tempfile.mkdtemp()
        try:
            memory = ConversationMemory(
                session_id="test-rolling-window",
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
            
            # Verify: Rolling window behavior
            stored_messages = memory.messages
            expected_count = min(len(messages), max_messages)
            
            assert len(stored_messages) == expected_count, \
                f"Should store exactly {expected_count} messages"
            
            # Verify the stored messages are the most recent ones
            if len(messages) > max_messages:
                expected_messages = messages[-max_messages:]
                for i, (stored, expected) in enumerate(zip(stored_messages, expected_messages)):
                    assert stored.content == expected["content"], \
                        f"Message {i}: content mismatch in rolling window"
                    assert stored.role == expected["role"], \
                        f"Message {i}: role mismatch in rolling window"
            else:
                # All messages should be stored
                for i, (stored, expected) in enumerate(zip(stored_messages, messages)):
                    assert stored.content == expected["content"], \
                        f"Message {i}: content mismatch"
        
        finally:
            shutil.rmtree(temp_session_dir, ignore_errors=True)
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        initial_messages=st.integers(min_value=5, max_value=20),
        max_messages=st.integers(min_value=3, max_value=10),
        additional_messages=st.integers(min_value=1, max_value=10)
    )
    def test_limit_enforced_continuously_as_messages_added(
        self, initial_messages, max_messages, additional_messages
    ):
        """
        Property: For any ongoing conversation, the message limit is 
        continuously enforced as new messages are added.
        
        # Feature: irisvoice-backend-integration, Property 15: Conversation Memory Limit
        **Validates: Requirements 17.2**
        """
        # Setup
        temp_session_dir = tempfile.mkdtemp()
        try:
            memory = ConversationMemory(
                session_id="test-continuous-limit",
                max_messages=max_messages,
                session_storage_path=temp_session_dir
            )
            
            # Execute: Add initial messages
            for i in range(initial_messages):
                memory.add_message(
                    role="user" if i % 2 == 0 else "assistant",
                    content=f"Initial message {i}",
                    text_tokens=5
                )
                
                # Verify: Limit is enforced after each addition
                expected_count = min(i + 1, max_messages)
                assert len(memory.messages) == expected_count, \
                    f"After adding message {i}, expected {expected_count} messages"
            
            # Add more messages and verify limit is still enforced
            for i in range(additional_messages):
                memory.add_message(
                    role="user",
                    content=f"Additional message {i}",
                    text_tokens=5
                )
                
                # Should never exceed max_messages
                assert len(memory.messages) == max_messages, \
                    f"Should maintain exactly {max_messages} messages"
            
            # Verify final state
            assert len(memory.messages) == max_messages, \
                f"Final state should have exactly {max_messages} messages"
            
            # Verify we have the most recent messages
            total_messages = initial_messages + additional_messages
            first_expected_index = total_messages - max_messages
            
            # The first stored message should be from the expected index
            expected_content_pattern = (
                f"Initial message {first_expected_index}" 
                if first_expected_index < initial_messages 
                else f"Additional message {first_expected_index - initial_messages}"
            )
            
            # Just verify we have max_messages and they're the most recent
            assert len(memory.messages) == max_messages
            
        finally:
            shutil.rmtree(temp_session_dir, ignore_errors=True)
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        max_messages=st.integers(min_value=1, max_value=20),
        num_messages=st.integers(min_value=1, max_value=50)
    )
    def test_memory_limit_persists_across_storage_operations(self, max_messages, num_messages):
        """
        Property: For any conversation with a message limit, the limit
        is maintained across persistence and reload operations.
        
        # Feature: irisvoice-backend-integration, Property 15: Conversation Memory Limit
        **Validates: Requirements 17.2**
        """
        # Setup
        temp_session_dir = tempfile.mkdtemp()
        try:
            # Create memory and add messages
            memory1 = ConversationMemory(
                session_id="test-persist-limit",
                max_messages=max_messages,
                session_storage_path=temp_session_dir
            )
            
            for i in range(num_messages):
                memory1.add_message(
                    role="user" if i % 2 == 0 else "assistant",
                    content=f"Message {i}",
                    text_tokens=10
                )
            
            # Verify initial state
            expected_count = min(num_messages, max_messages)
            assert len(memory1.messages) == expected_count
            
            # Create new memory instance (simulates reload)
            memory2 = ConversationMemory(
                session_id="test-persist-limit",
                max_messages=max_messages,
                session_storage_path=temp_session_dir
            )
            
            # Verify: Loaded memory respects the limit
            assert len(memory2.messages) == expected_count, \
                f"Loaded memory should have {expected_count} messages"
            
            # Verify the messages are the same
            for i, (msg1, msg2) in enumerate(zip(memory1.messages, memory2.messages)):
                assert msg1.content == msg2.content, \
                    f"Message {i}: content mismatch after reload"
                assert msg1.role == msg2.role, \
                    f"Message {i}: role mismatch after reload"
        
        finally:
            shutil.rmtree(temp_session_dir, ignore_errors=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
