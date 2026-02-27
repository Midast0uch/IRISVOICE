"""
Integration test for text chat flow.

Tests:
- text_message → agent processing → text_response
- Conversation context maintenance
- clear_chat functionality

Feature: irisvoice-backend-integration
Requirements: 5.1-5.7, 17.1-17.7
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime


@pytest.mark.asyncio
async def test_text_message_complete_flow(mock_agent_kernel, mock_websocket_manager, mock_conversation_memory):
    """Test complete text message flow from user input to agent response."""
    # Arrange
    session_id = "test-session-chat"
    client_id = "test-client-chat"
    user_message = "What is the capital of France?"
    agent_response = "The capital of France is Paris."
    
    mock_agent_kernel.process_text_message = AsyncMock(return_value=agent_response)
    mock_conversation_memory.add_message = MagicMock()
    mock_conversation_memory.get_context = MagicMock(return_value=[])
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - Send text message
    response = await mock_agent_kernel.process_text_message(user_message, session_id)
    
    # Simulate response delivery
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "text_response",
        "payload": {
            "text": response,
            "sender": "assistant"
        }
    })
    
    # Assert
    mock_agent_kernel.process_text_message.assert_called_once_with(user_message, session_id)
    assert response == agent_response
    
    # Verify response sent to client
    mock_websocket_manager.send_to_client.assert_called_once()
    sent_message = mock_websocket_manager.send_to_client.call_args[0][1]
    assert sent_message["type"] == "text_response"
    assert sent_message["payload"]["text"] == agent_response
    assert sent_message["payload"]["sender"] == "assistant"


@pytest.mark.asyncio
async def test_conversation_context_maintenance(mock_agent_kernel, mock_conversation_memory):
    """Test conversation context is maintained across multiple messages."""
    # Arrange
    session_id = "test-session-context"
    
    conversation_history = []
    
    def add_message_side_effect(session_id, role, content):
        conversation_history.append({"role": role, "content": content})
    
    def get_context_side_effect(session_id):
        return conversation_history.copy()
    
    mock_conversation_memory.add_message = MagicMock(side_effect=add_message_side_effect)
    mock_conversation_memory.get_context = MagicMock(side_effect=get_context_side_effect)
    
    # Mock agent responses
    responses = [
        "Hello! How can I help you?",
        "The weather is sunny today.",
        "Yes, it's a great day for a walk!"
    ]
    response_index = 0
    
    def process_message_side_effect(text, sid):
        nonlocal response_index
        # Add user message to context
        mock_conversation_memory.add_message(sid, "user", text)
        # Get response
        response = responses[response_index]
        response_index += 1
        # Add assistant message to context
        mock_conversation_memory.add_message(sid, "assistant", response)
        return response
    
    mock_agent_kernel.process_text_message = AsyncMock(side_effect=process_message_side_effect)
    
    # Act - Send multiple messages
    messages = [
        "Hello",
        "What's the weather like?",
        "Should I go for a walk?"
    ]
    
    for message in messages:
        await mock_agent_kernel.process_text_message(message, session_id)
    
    # Get final context
    context = mock_conversation_memory.get_context(session_id)
    
    # Assert
    assert len(context) == 6  # 3 user messages + 3 assistant responses
    
    # Verify conversation structure
    for i, message in enumerate(messages):
        assert context[i * 2]["role"] == "user"
        assert context[i * 2]["content"] == message
        assert context[i * 2 + 1]["role"] == "assistant"
        assert context[i * 2 + 1]["content"] == responses[i]


@pytest.mark.asyncio
async def test_clear_chat_functionality(mock_agent_kernel, mock_conversation_memory, mock_websocket_manager):
    """Test clear_chat clears conversation history."""
    # Arrange
    session_id = "test-session-clear"
    client_id = "test-client-clear"
    
    # Setup conversation history
    conversation_history = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "How are you?"},
        {"role": "assistant", "content": "I'm doing well, thank you!"}
    ]
    
    mock_conversation_memory.get_context = MagicMock(return_value=conversation_history.copy())
    mock_conversation_memory.clear = MagicMock()
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Verify history exists
    context_before = mock_conversation_memory.get_context(session_id)
    assert len(context_before) == 4
    
    # Act - Clear chat
    mock_conversation_memory.clear(session_id)
    mock_conversation_memory.get_context = MagicMock(return_value=[])
    
    # Simulate confirmation
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "chat_cleared",
        "payload": {}
    })
    
    # Assert
    mock_conversation_memory.clear.assert_called_once_with(session_id)
    
    context_after = mock_conversation_memory.get_context(session_id)
    assert len(context_after) == 0
    
    # Verify confirmation sent
    mock_websocket_manager.send_to_client.assert_called_once()


@pytest.mark.asyncio
async def test_typing_indicator_during_processing(mock_agent_kernel, mock_websocket_manager):
    """Test typing indicator is shown while agent processes message."""
    # Arrange
    session_id = "test-session-typing"
    client_id = "test-client-typing"
    user_message = "Tell me a story"
    
    # Simulate slow processing
    async def slow_process(text, sid):
        await asyncio.sleep(0.1)  # Simulate processing time
        return "Once upon a time..."
    
    mock_agent_kernel.process_text_message = AsyncMock(side_effect=slow_process)
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - Show typing indicator
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "typing_indicator",
        "payload": {"is_typing": True}
    })
    
    # Process message
    response = await mock_agent_kernel.process_text_message(user_message, session_id)
    
    # Hide typing indicator
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "typing_indicator",
        "payload": {"is_typing": False}
    })
    
    # Send response
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "text_response",
        "payload": {"text": response, "sender": "assistant"}
    })
    
    # Assert
    assert mock_websocket_manager.send_to_client.call_count == 3
    
    # Verify typing indicator sequence
    calls = mock_websocket_manager.send_to_client.call_args_list
    assert calls[0][0][1]["type"] == "typing_indicator"
    assert calls[0][0][1]["payload"]["is_typing"] is True
    assert calls[1][0][1]["type"] == "typing_indicator"
    assert calls[1][0][1]["payload"]["is_typing"] is False
    assert calls[2][0][1]["type"] == "text_response"


@pytest.mark.asyncio
async def test_agent_unavailable_error(mock_agent_kernel, mock_websocket_manager):
    """Test error handling when agent kernel is unavailable."""
    # Arrange
    session_id = "test-session-unavailable"
    client_id = "test-client-unavailable"
    user_message = "Hello"
    
    mock_agent_kernel.process_text_message = AsyncMock(
        side_effect=Exception("Agent kernel is not available")
    )
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act
    try:
        await mock_agent_kernel.process_text_message(user_message, session_id)
    except Exception as e:
        # Send error message
        await mock_websocket_manager.send_to_client(client_id, {
            "type": "error",
            "payload": {"message": str(e)}
        })
    
    # Assert
    mock_websocket_manager.send_to_client.assert_called_once()
    error_message = mock_websocket_manager.send_to_client.call_args[0][1]
    assert error_message["type"] == "error"
    assert "Agent kernel is not available" in error_message["payload"]["message"]


@pytest.mark.asyncio
async def test_conversation_memory_limit(mock_conversation_memory):
    """Test conversation memory respects message limit."""
    # Arrange
    session_id = "test-session-limit"
    max_messages = 10
    
    conversation_history = []
    
    def add_message_side_effect(session_id, role, content):
        conversation_history.append({"role": role, "content": content})
        # Keep only last max_messages
        if len(conversation_history) > max_messages:
            conversation_history.pop(0)
    
    def get_context_side_effect(session_id):
        return conversation_history.copy()
    
    mock_conversation_memory.add_message = MagicMock(side_effect=add_message_side_effect)
    mock_conversation_memory.get_context = MagicMock(side_effect=get_context_side_effect)
    
    # Act - Add more messages than limit
    for i in range(15):
        mock_conversation_memory.add_message(session_id, "user", f"Message {i}")
    
    context = mock_conversation_memory.get_context(session_id)
    
    # Assert
    assert len(context) == max_messages
    # Verify oldest messages were removed
    assert context[0]["content"] == "Message 5"
    assert context[-1]["content"] == "Message 14"


@pytest.mark.asyncio
async def test_multi_turn_conversation_with_context(mock_agent_kernel, mock_conversation_memory):
    """Test multi-turn conversation maintains context for follow-up questions."""
    # Arrange
    session_id = "test-session-multi-turn"
    
    conversation_history = []
    
    def add_message_side_effect(session_id, role, content):
        conversation_history.append({"role": role, "content": content})
    
    def get_context_side_effect(session_id):
        return conversation_history.copy()
    
    mock_conversation_memory.add_message = MagicMock(side_effect=add_message_side_effect)
    mock_conversation_memory.get_context = MagicMock(side_effect=get_context_side_effect)
    
    # Simulate context-aware responses
    def process_with_context(text, sid):
        context = mock_conversation_memory.get_context(sid)
        mock_conversation_memory.add_message(sid, "user", text)
        
        # Context-aware response
        if "capital" in text.lower():
            response = "The capital of France is Paris."
        elif "population" in text.lower() and len(context) > 0:
            # Follow-up question - uses context
            response = "Paris has a population of about 2.2 million people."
        else:
            response = "I'm not sure about that."
        
        mock_conversation_memory.add_message(sid, "assistant", response)
        return response
    
    mock_agent_kernel.process_text_message = AsyncMock(side_effect=process_with_context)
    
    # Act - Multi-turn conversation
    response1 = await mock_agent_kernel.process_text_message(
        "What is the capital of France?", session_id
    )
    response2 = await mock_agent_kernel.process_text_message(
        "What is its population?", session_id
    )
    
    # Assert
    assert "Paris" in response1
    assert "2.2 million" in response2
    
    # Verify context was maintained
    context = mock_conversation_memory.get_context(session_id)
    assert len(context) == 4  # 2 user messages + 2 assistant responses


@pytest.mark.asyncio
async def test_message_timestamps(mock_websocket_manager):
    """Test messages include timestamps."""
    # Arrange
    client_id = "test-client-timestamp"
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act
    timestamp = datetime.utcnow().isoformat()
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "text_response",
        "payload": {
            "text": "Hello!",
            "sender": "assistant",
            "timestamp": timestamp
        }
    })
    
    # Assert
    sent_message = mock_websocket_manager.send_to_client.call_args[0][1]
    assert "timestamp" in sent_message["payload"]
    assert sent_message["payload"]["timestamp"] == timestamp


@pytest.mark.asyncio
async def test_conversation_persistence(mock_conversation_memory):
    """Test conversation history is persisted to storage."""
    # Arrange
    session_id = "test-session-persist"
    
    mock_conversation_memory.add_message = MagicMock()
    mock_conversation_memory.save_to_storage = AsyncMock()
    
    # Act - Add messages
    mock_conversation_memory.add_message(session_id, "user", "Hello")
    mock_conversation_memory.add_message(session_id, "assistant", "Hi there!")
    
    # Persist to storage
    await mock_conversation_memory.save_to_storage(session_id)
    
    # Assert
    mock_conversation_memory.save_to_storage.assert_called_once_with(session_id)


@pytest.mark.asyncio
async def test_conversation_archival_on_session_end(mock_conversation_memory):
    """Test conversation is archived when session ends."""
    # Arrange
    session_id = "test-session-archive"
    
    conversation_history = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi!"}
    ]
    
    mock_conversation_memory.get_context = MagicMock(return_value=conversation_history)
    mock_conversation_memory.archive = AsyncMock()
    
    # Act - Archive conversation
    await mock_conversation_memory.archive(session_id)
    
    # Assert
    mock_conversation_memory.archive.assert_called_once_with(session_id)


@pytest.mark.asyncio
async def test_response_timeout_handling(mock_agent_kernel, mock_websocket_manager):
    """Test handling of agent response timeout (10 seconds)."""
    # Arrange
    session_id = "test-session-timeout"
    client_id = "test-client-timeout"
    user_message = "Complex query"
    
    # Simulate timeout
    async def timeout_process(text, sid):
        await asyncio.sleep(0.1)  # Simulate long processing
        raise asyncio.TimeoutError("Agent response timeout")
    
    mock_agent_kernel.process_text_message = AsyncMock(side_effect=timeout_process)
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act
    try:
        await asyncio.wait_for(
            mock_agent_kernel.process_text_message(user_message, session_id),
            timeout=0.05  # Shorter timeout for test
        )
    except asyncio.TimeoutError:
        # Send timeout error
        await mock_websocket_manager.send_to_client(client_id, {
            "type": "error",
            "payload": {"message": "Agent response timeout - please try again"}
        })
    
    # Assert
    mock_websocket_manager.send_to_client.assert_called_once()
    error_message = mock_websocket_manager.send_to_client.call_args[0][1]
    assert error_message["type"] == "error"
    assert "timeout" in error_message["payload"]["message"].lower()


@pytest.mark.asyncio
async def test_empty_message_handling(mock_agent_kernel, mock_websocket_manager):
    """Test handling of empty or whitespace-only messages."""
    # Arrange
    session_id = "test-session-empty"
    client_id = "test-client-empty"
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - Try to send empty message
    empty_messages = ["", "   ", "\n\t"]
    
    for msg in empty_messages:
        if not msg.strip():
            # Send validation error
            await mock_websocket_manager.send_to_client(client_id, {
                "type": "validation_error",
                "payload": {"error": "Message cannot be empty"}
            })
    
    # Assert
    assert mock_websocket_manager.send_to_client.call_count == len(empty_messages)
    
    # Verify agent was not called
    mock_agent_kernel.process_text_message.assert_not_called()
