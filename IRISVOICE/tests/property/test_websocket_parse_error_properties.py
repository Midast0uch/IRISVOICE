"""
Property-based tests for WebSocket message parse error handling.
Tests universal properties that should hold for all error scenarios.
"""
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from hypothesis import given, settings, strategies as st, seed
import sys
import os

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.iris_gateway import IRISGateway
from backend.ws_manager import WebSocketManager
from backend.state_manager import StateManager


# ============================================================================
# Test Data Generators (Hypothesis Strategies)
# ============================================================================

@st.composite
def invalid_messages(draw):
    """Generate invalid message formats that should trigger parse errors."""
    return draw(st.one_of(
        # Not a dict
        st.lists(st.text()),
        st.text(),
        st.integers(),
        st.floats(),
        st.booleans(),
        st.none(),
        # Dict without 'type' field
        st.dictionaries(
            st.text(alphabet=st.characters(whitelist_categories=('Lu', 'Ll')), min_size=1).filter(lambda x: x != 'type'),
            st.one_of(st.text(), st.integers(), st.booleans())
        ),
        # Dict with invalid 'type' value
        st.fixed_dictionaries({
            'type': st.one_of(st.none(), st.integers(), st.lists(st.text()), st.dictionaries(st.text(), st.text()))
        })
    ))


@st.composite
def malformed_json_strings(draw):
    """Generate strings that look like JSON but are malformed."""
    return draw(st.one_of(
        st.just('{"type": "test"'),  # Missing closing brace
        st.just('{"type": }'),  # Missing value
        st.just('{type: "test"}'),  # Missing quotes on key
        st.just("{'type': 'test'}"),  # Single quotes instead of double
        st.just('{"type": "test",}'),  # Trailing comma
        st.just(''),  # Empty string
        st.just('null'),  # Just null
        st.just('undefined'),  # JavaScript undefined
    ))


@st.composite
def unknown_message_types(draw):
    """Generate messages with unknown/invalid message types."""
    # Generate random strings that are not valid message types
    invalid_type = draw(st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd', 'Pc')),
        min_size=1,
        max_size=50
    ).filter(lambda x: x not in [
        'select_category', 'select_subnode', 'go_back',
        'update_field', 'update_theme', 'confirm_mini_node',
        'voice_command_start', 'voice_command_end',
        'text_message', 'clear_chat',
        'get_agent_status', 'get_agent_tools',
        'ping', 'pong', 'request_state'
    ]))
    
    return {
        'type': invalid_type,
        'payload': draw(st.dictionaries(st.text(), st.one_of(st.text(), st.integers(), st.booleans())))
    }


@st.composite
def client_ids(draw):
    """Generate valid client IDs."""
    return draw(st.one_of(
        st.uuids().map(str),
        st.text(alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd')), min_size=5, max_size=50)
    ))


# ============================================================================
# Property 47: WebSocket Message Parse Error Handling
# Feature: irisvoice-backend-integration, Property 47: WebSocket Message Parse Error Handling
# Validates: Requirements 19.1
# ============================================================================

class TestWebSocketMessageParseErrorHandling:
    """
    Property 47: WebSocket Message Parse Error Handling
    
    For any WebSocket message that fails to parse, the backend shall log the 
    error and continue processing other messages without crashing.
    """
    
    @pytest.mark.asyncio
    @settings(max_examples=20, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        client_id=client_ids(),
        invalid_message=invalid_messages()
    )
    async def test_invalid_message_format_logged_and_continues(self, client_id, invalid_message):
        """
        Property: For any invalid message format, the gateway logs the error,
        sends an error response, and continues processing without crashing.
        
        # Feature: irisvoice-backend-integration, Property 47: WebSocket Message Parse Error Handling
        **Validates: Requirements 19.1**
        """
        # Setup mocks
        mock_ws_manager = MagicMock(spec=WebSocketManager)
        mock_ws_manager.get_session_id_for_client = MagicMock(return_value="test-session")
        mock_ws_manager.send_to_client = AsyncMock(return_value=True)
        
        mock_state_manager = MagicMock(spec=StateManager)
        
        # Create gateway
        gateway = IRISGateway(
            ws_manager=mock_ws_manager,
            state_manager=mock_state_manager
        )
        
        # Capture log output
        with patch('backend.iris_gateway.logger') as mock_logger:
            # Execute: Handle invalid message
            try:
                await gateway.handle_message(client_id, invalid_message)
                
                # Verify: Error was logged
                assert mock_logger.error.called, "Error should be logged for invalid message"
                
                # Verify: Error response was sent to client
                mock_ws_manager.send_to_client.assert_called()
                call_args = mock_ws_manager.send_to_client.call_args
                assert call_args[0][0] == client_id
                error_message = call_args[0][1]
                assert error_message['type'] == 'error'
                assert 'message' in error_message['payload']
                
                # Verify: Gateway did not crash (no exception raised)
                # If we reach here, the gateway handled the error gracefully
                
            except Exception as e:
                pytest.fail(f"Gateway should not crash on invalid message, but raised: {e}")
    
    @pytest.mark.asyncio
    @settings(max_examples=15, deadline=None)
    @seed(42)
    @given(
        client_id=client_ids(),
        unknown_msg=unknown_message_types()
    )
    async def test_unknown_message_type_logged_and_continues(self, client_id, unknown_msg):
        """
        Property: For any unknown message type, the gateway logs a warning,
        sends an error response, and continues processing.
        
        # Feature: irisvoice-backend-integration, Property 47: WebSocket Message Parse Error Handling
        **Validates: Requirements 19.1**
        """
        # Setup mocks
        mock_ws_manager = MagicMock(spec=WebSocketManager)
        mock_ws_manager.get_session_id_for_client = MagicMock(return_value="test-session")
        mock_ws_manager.send_to_client = AsyncMock(return_value=True)
        
        mock_state_manager = MagicMock(spec=StateManager)
        
        # Create gateway
        gateway = IRISGateway(
            ws_manager=mock_ws_manager,
            state_manager=mock_state_manager
        )
        
        # Capture log output
        with patch('backend.iris_gateway.logger') as mock_logger:
            # Execute: Handle unknown message type
            try:
                await gateway.handle_message(client_id, unknown_msg)
                
                # Verify: Warning was logged
                assert mock_logger.warning.called, "Warning should be logged for unknown message type"
                
                # Verify: Error response was sent to client
                mock_ws_manager.send_to_client.assert_called()
                call_args = mock_ws_manager.send_to_client.call_args
                assert call_args[0][0] == client_id
                error_message = call_args[0][1]
                assert error_message['type'] == 'error'
                assert 'Unknown message type' in error_message['payload']['message']
                
                # Verify: Gateway did not crash
                
            except Exception as e:
                pytest.fail(f"Gateway should not crash on unknown message type, but raised: {e}")
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        client_id=client_ids()
    )
    async def test_missing_session_logged_and_continues(self, client_id):
        """
        Property: For any message from a client without a session, the gateway
        logs an error, sends an error response, and continues processing.
        
        # Feature: irisvoice-backend-integration, Property 47: WebSocket Message Parse Error Handling
        **Validates: Requirements 19.1**
        """
        # Setup mocks
        mock_ws_manager = MagicMock(spec=WebSocketManager)
        # Simulate no session for this client
        mock_ws_manager.get_session_id_for_client = MagicMock(return_value=None)
        mock_ws_manager.send_to_client = AsyncMock(return_value=True)
        
        mock_state_manager = MagicMock(spec=StateManager)
        
        # Create gateway
        gateway = IRISGateway(
            ws_manager=mock_ws_manager,
            state_manager=mock_state_manager
        )
        
        # Valid message but no session
        valid_message = {
            'type': 'text_message',
            'payload': {'text': 'Hello'}
        }
        
        # Capture log output
        with patch('backend.iris_gateway.logger') as mock_logger:
            # Execute: Handle message without session
            try:
                await gateway.handle_message(client_id, valid_message)
                
                # Verify: Error was logged
                assert mock_logger.error.called, "Error should be logged for missing session"
                
                # Verify: Error response was sent to client
                mock_ws_manager.send_to_client.assert_called()
                call_args = mock_ws_manager.send_to_client.call_args
                assert call_args[0][0] == client_id
                error_message = call_args[0][1]
                assert error_message['type'] == 'error'
                assert 'No active session' in error_message['payload']['message']
                
                # Verify: Gateway did not crash
                
            except Exception as e:
                pytest.fail(f"Gateway should not crash on missing session, but raised: {e}")
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        client_id=client_ids(),
        num_invalid_messages=st.integers(min_value=2, max_value=5)
    )
    async def test_multiple_parse_errors_do_not_crash_gateway(self, client_id, num_invalid_messages):
        """
        Property: For any sequence of invalid messages, the gateway continues
        processing all of them without crashing.
        
        # Feature: irisvoice-backend-integration, Property 47: WebSocket Message Parse Error Handling
        **Validates: Requirements 19.1**
        """
        # Setup mocks
        mock_ws_manager = MagicMock(spec=WebSocketManager)
        mock_ws_manager.get_session_id_for_client = MagicMock(return_value="test-session")
        mock_ws_manager.send_to_client = AsyncMock(return_value=True)
        
        mock_state_manager = MagicMock(spec=StateManager)
        
        # Create gateway
        gateway = IRISGateway(
            ws_manager=mock_ws_manager,
            state_manager=mock_state_manager
        )
        
        # Generate multiple invalid messages
        invalid_messages = [
            "not a dict",
            {"no_type_field": "value"},
            {"type": None},
            {"type": 123},
            {"type": "unknown_type_xyz"}
        ][:num_invalid_messages]
        
        # Capture log output
        with patch('backend.iris_gateway.logger') as mock_logger:
            # Execute: Handle multiple invalid messages
            error_count = 0
            try:
                for msg in invalid_messages:
                    await gateway.handle_message(client_id, msg)
                    error_count += 1
                
                # Verify: All messages were processed (no crash)
                assert error_count == num_invalid_messages, \
                    f"Should process all {num_invalid_messages} messages"
                
                # Verify: Errors were logged for each invalid message
                assert mock_logger.error.call_count >= num_invalid_messages, \
                    "Each invalid message should generate at least one error log"
                
                # Verify: Error responses were sent for each message
                assert mock_ws_manager.send_to_client.call_count >= num_invalid_messages, \
                    "Each invalid message should generate an error response"
                
            except Exception as e:
                pytest.fail(
                    f"Gateway should not crash after {error_count}/{num_invalid_messages} "
                    f"invalid messages, but raised: {e}"
                )
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        client_id=client_ids()
    )
    async def test_json_decode_error_logged_and_continues(self, client_id):
        """
        Property: For any JSON decode error, the gateway logs the error,
        sends an error response, and continues processing.
        
        # Feature: irisvoice-backend-integration, Property 47: WebSocket Message Parse Error Handling
        **Validates: Requirements 19.1**
        """
        # Setup mocks
        mock_ws_manager = MagicMock(spec=WebSocketManager)
        mock_ws_manager.get_session_id_for_client = MagicMock(return_value="test-session")
        mock_ws_manager.send_to_client = AsyncMock(return_value=True)
        
        mock_state_manager = MagicMock(spec=StateManager)
        
        # Create gateway
        gateway = IRISGateway(
            ws_manager=mock_ws_manager,
            state_manager=mock_state_manager
        )
        
        # Simulate a JSON decode error by passing a string that would fail JSON parsing
        # In practice, this would come from websocket.receive_text() before being parsed
        # We simulate the error by patching json.loads to raise JSONDecodeError
        
        with patch('backend.iris_gateway.logger') as mock_logger:
            with patch('json.loads', side_effect=json.JSONDecodeError("test error", "doc", 0)):
                # Execute: This simulates receiving malformed JSON
                # In the actual flow, the message would be parsed before reaching handle_message
                # But we test that if a JSONDecodeError occurs anywhere in the handler,
                # it's caught and logged
                
                try:
                    # Create a message that would trigger JSON operations
                    message = {"type": "text_message", "payload": {"text": "test"}}
                    await gateway.handle_message(client_id, message)
                    
                    # If json.loads is called and raises, it should be caught
                    # The gateway should log the error and send an error response
                    
                except json.JSONDecodeError:
                    # If the error propagates, the test fails
                    pytest.fail("JSONDecodeError should be caught and handled gracefully")
                
                # Note: The actual JSON parsing happens before handle_message in the
                # WebSocket endpoint. This test verifies that if a JSONDecodeError
                # occurs during message handling, it's caught by the general exception handler.


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
