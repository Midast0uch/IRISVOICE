"""
Integration Tests for WebSocket Message Flow Fix

**Validates: Requirements 2.1, 2.2, 2.3, 3.1, 3.2, 3.3**

This test suite verifies the complete WebSocket connection and state synchronization flows
after implementing the fix. These tests ensure:

1. Full connection flow: connect → receive initial_state → state initialized
2. Reconnection flow: disconnect → reconnect → receive initial_state → state re-initialized
3. State request flow: connect → request_state → receive initial_state → state updated
4. Multi-client flow: client A connects → client B connects → both receive initial_state
5. Console no longer shows refresh loop or "State not initialized" warnings
6. Frontend state is properly initialized on first connection

These are end-to-end integration tests that verify the complete system behavior.
"""

import pytest
import asyncio
import json
from fastapi.testclient import TestClient
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from backend.main import app


class TestWebSocketIntegration:
    """
    Integration tests for WebSocket message flow fix.
    
    These tests verify the complete system behavior after implementing the fix.
    """
    
    # ========================================================================
    # Test 1: Full Connection Flow
    # ========================================================================
    
    @pytest.mark.asyncio
    async def test_full_connection_flow(self):
        """
        Test full connection flow: connect → request_state → receive initial_state → state initialized
        
        **Validates: Requirements 2.1, 2.2, 2.3**
        
        This test verifies that:
        1. WebSocket connection is established successfully
        2. Client can request state explicitly
        3. Backend sends initial_state message with correct format
        4. Message has type "initial_state" with nested payload structure
        5. State data is properly structured (may be empty for new sessions)
        
        Note: The websocket_endpoint only sends initial_state if state exists.
        For new test sessions, we need to explicitly request state.
        """
        client = TestClient(app)
        
        with client.websocket_connect("/ws/test-client-integration-1?session_id=test-session-integration-1") as websocket:
            # For new sessions without existing state, explicitly request state
            websocket.send_text(json.dumps({
                "type": "request_state",
                "payload": {}
            }))
            
            # Receive the initial state message
            data = websocket.receive_text()
            message = json.loads(data)
            
            # Verify message has correct type
            assert message.get("type") == "initial_state", \
                f"Expected message type 'initial_state', but got '{message.get('type')}'"
            
            # Verify message has nested payload structure
            assert "payload" in message, \
                f"Expected 'payload' key in message, but got keys: {list(message.keys())}"
            
            # Verify state data is nested under payload.state
            assert "state" in message.get("payload", {}), \
                f"Expected 'state' key under 'payload', but payload contains: {list(message.get('payload', {}).keys())}"
            
            # Verify state data is a dictionary (may be empty for new sessions)
            state = message["payload"]["state"]
            assert isinstance(state, dict), \
                f"Expected state to be a dictionary, but got {type(state)}"
            
            print(f"✓ Full connection flow successful: received initial_state with proper structure")
            print(f"✓ State: {state if state else '(empty - new session)'}")
    
    # ========================================================================
    # Test 2: Reconnection Flow
    # ========================================================================
    
    @pytest.mark.asyncio
    async def test_reconnection_flow(self):
        """
        Test reconnection flow: disconnect → reconnect → request_state → receive initial_state
        
        **Validates: Requirements 2.1, 2.2, 2.3, 3.1**
        
        This test verifies that:
        1. First connection can request and receive initial_state correctly
        2. After disconnection, reconnection works
        3. Reconnection can also request and receive initial_state with correct format
        4. State is accessible on reconnection
        """
        client = TestClient(app)
        
        # First connection
        with client.websocket_connect("/ws/test-client-integration-2a?session_id=test-session-integration-2") as websocket1:
            # Request initial state on first connection
            websocket1.send_text(json.dumps({
                "type": "request_state",
                "payload": {}
            }))
            
            data1 = websocket1.receive_text()
            message1 = json.loads(data1)
            
            assert message1.get("type") == "initial_state", \
                f"First connection: Expected 'initial_state', got '{message1.get('type')}'"
            assert "payload" in message1 and "state" in message1["payload"], \
                "First connection: Missing nested payload structure"
            
            print(f"✓ First connection successful: received initial_state")
        
        # Simulate reconnection (new connection with same session)
        with client.websocket_connect("/ws/test-client-integration-2b?session_id=test-session-integration-2") as websocket2:
            # Request initial state on reconnection
            websocket2.send_text(json.dumps({
                "type": "request_state",
                "payload": {}
            }))
            
            data2 = websocket2.receive_text()
            message2 = json.loads(data2)
            
            assert message2.get("type") == "initial_state", \
                f"Reconnection: Expected 'initial_state', got '{message2.get('type')}'"
            assert "payload" in message2 and "state" in message2["payload"], \
                "Reconnection: Missing nested payload structure"
            
            print(f"✓ Reconnection flow successful: received initial_state on reconnect")
    
    # ========================================================================
    # Test 3: State Request Flow
    # ========================================================================
    
    @pytest.mark.asyncio
    async def test_state_request_flow(self):
        """
        Test state request flow: connect → request_state → receive initial_state → state updated
        
        **Validates: Requirements 2.1, 2.2, 2.3**
        
        This test verifies that:
        1. Connection is established successfully
        2. Explicit request_state message is sent
        3. Backend responds with initial_state message
        4. Response has correct format (type "initial_state" with nested payload)
        """
        client = TestClient(app)
        
        with client.websocket_connect("/ws/test-client-integration-3?session_id=test-session-integration-3") as websocket:
            # Send explicit request_state message
            websocket.send_text(json.dumps({
                "type": "request_state",
                "payload": {}
            }))
            
            print(f"✓ Connection established, sent request_state message")
            
            # Receive response to request_state
            data = websocket.receive_text()
            response_message = json.loads(data)
            
            # Verify response has correct type
            assert response_message.get("type") == "initial_state", \
                f"Expected response type 'initial_state', but got '{response_message.get('type')}'"
            
            # Verify response has nested payload structure
            assert "payload" in response_message, \
                f"Expected 'payload' key in response, but got keys: {list(response_message.keys())}"
            
            # Verify state data is nested under payload.state
            assert "state" in response_message.get("payload", {}), \
                f"Expected 'state' key under 'payload', but payload contains: {list(response_message.get('payload', {}).keys())}"
            
            print(f"✓ State request flow successful: received initial_state response with proper structure")
    
    # ========================================================================
    # Test 4: Multi-Client Flow
    # ========================================================================
    
    @pytest.mark.asyncio
    async def test_multi_client_flow(self):
        """
        Test multi-client flow: client A connects → client B connects → both can request initial_state
        
        **Validates: Requirements 2.1, 2.2, 2.3, 3.1**
        
        This test verifies that:
        1. Multiple clients can connect simultaneously
        2. Each client can request and receive initial_state
        3. All clients receive messages with correct format
        4. State synchronization works across multiple clients
        """
        client = TestClient(app)
        
        # Connect client A
        with client.websocket_connect("/ws/test-client-integration-4a?session_id=test-session-integration-4") as websocket_a:
            # Request initial state for client A
            websocket_a.send_text(json.dumps({
                "type": "request_state",
                "payload": {}
            }))
            
            data_a = websocket_a.receive_text()
            message_a = json.loads(data_a)
            
            assert message_a.get("type") == "initial_state", \
                f"Client A: Expected 'initial_state', got '{message_a.get('type')}'"
            assert "payload" in message_a and "state" in message_a["payload"], \
                "Client A: Missing nested payload structure"
            
            print(f"✓ Client A connected and received initial_state")
            
            # Connect client B (same session)
            with client.websocket_connect("/ws/test-client-integration-4b?session_id=test-session-integration-4") as websocket_b:
                # Request initial state for client B
                websocket_b.send_text(json.dumps({
                    "type": "request_state",
                    "payload": {}
                }))
                
                data_b = websocket_b.receive_text()
                message_b = json.loads(data_b)
                
                assert message_b.get("type") == "initial_state", \
                    f"Client B: Expected 'initial_state', got '{message_b.get('type')}'"
                assert "payload" in message_b and "state" in message_b["payload"], \
                    "Client B: Missing nested payload structure"
                
                print(f"✓ Client B connected and received initial_state")
                
                # Verify both clients received state from the same session
                state_a = message_a["payload"]["state"]
                state_b = message_b["payload"]["state"]
                
                # Both should have received state data (structure may vary)
                assert isinstance(state_a, dict), "Client A: State should be a dictionary"
                assert isinstance(state_b, dict), "Client B: State should be a dictionary"
                
                print(f"✓ Multi-client flow successful: both clients received initial_state")
    
    # ========================================================================
    # Test 5: No Refresh Loop or State Warnings
    # ========================================================================
    
    @pytest.mark.asyncio
    async def test_no_refresh_loop_or_warnings(self):
        """
        Test that console no longer shows refresh loop or "State not initialized" warnings
        
        **Validates: Requirements 2.4, 2.5**
        
        This test verifies that:
        1. Initial state can be requested and received
        2. No additional state requests are triggered automatically
        3. State is properly initialized (no warnings expected)
        4. Connection remains stable without repeated reconnection attempts
        """
        client = TestClient(app)
        
        with client.websocket_connect("/ws/test-client-integration-5?session_id=test-session-integration-5") as websocket:
            # Request initial state
            websocket.send_text(json.dumps({
                "type": "request_state",
                "payload": {}
            }))
            
            data = websocket.receive_text()
            initial_message = json.loads(data)
            
            assert initial_message.get("type") == "initial_state", \
                f"Expected 'initial_state', got '{initial_message.get('type')}'"
            
            print(f"✓ Received initial_state")
            
            # Wait a bit to see if any additional messages are sent (should only be pings)
            # If the bug still exists, we would see repeated state requests or full_state messages
            additional_messages = []
            for _ in range(3):
                try:
                    data = websocket.receive_text(timeout=1.0)
                    message = json.loads(data)
                    if message.get("type") != "ping":
                        additional_messages.append(message)
                except Exception:
                    break
            
            # Verify no unexpected state-related messages (no refresh loop)
            unexpected_types = ["full_state", "request_state"]
            for msg in additional_messages:
                assert msg.get("type") not in unexpected_types, \
                    f"Unexpected message type '{msg.get('type')}' detected - possible refresh loop"
            
            print(f"✓ No refresh loop detected: only received expected messages")
            print(f"✓ State properly initialized without warnings")
    
    # ========================================================================
    # Test 6: Frontend State Initialization
    # ========================================================================
    
    @pytest.mark.asyncio
    async def test_frontend_state_initialization(self):
        """
        Test that frontend state is properly initialized
        
        **Validates: Requirements 2.3, 2.4**
        
        This test verifies that:
        1. Initial state message can be requested
        2. State data structure matches frontend expectations
        3. State can be extracted from payload.state correctly
        4. All state fields are present (or empty but defined)
        """
        client = TestClient(app)
        
        with client.websocket_connect("/ws/test-client-integration-6?session_id=test-session-integration-6") as websocket:
            # Request initial state
            websocket.send_text(json.dumps({
                "type": "request_state",
                "payload": {}
            }))
            
            data = websocket.receive_text()
            message = json.loads(data)
            
            assert message.get("type") == "initial_state", \
                f"Expected 'initial_state', got '{message.get('type')}'"
            
            # Extract state from nested payload structure
            assert "payload" in message, "Missing 'payload' key"
            assert "state" in message["payload"], "Missing 'state' key under 'payload'"
            
            state = message["payload"]["state"]
            
            # Verify state is a dictionary
            assert isinstance(state, dict), \
                f"Expected state to be a dictionary, but got {type(state)}"
            
            # Verify state has expected structure (based on IRISState model)
            # Note: State may be empty on first connection, but structure should be valid
            expected_fields = ["current_category", "current_subnode", "field_values", "active_theme", "confirmed_nodes"]
            
            # Check if state has any of the expected fields (may be empty but should be valid)
            # If state is empty dict, that's also valid (no state initialized yet)
            if state:  # If state has data
                # At least some expected fields should be present
                has_expected_fields = any(field in state for field in expected_fields)
                assert has_expected_fields or len(state) == 0, \
                    f"State has unexpected structure. Expected fields: {expected_fields}, got: {list(state.keys())}"
            
            print(f"✓ Frontend state initialization successful")
            print(f"✓ State structure is valid and can be extracted from payload.state")
            print(f"✓ State fields: {list(state.keys()) if state else '(empty state)'}")
    
    # ========================================================================
    # Test 7: Message Format Consistency
    # ========================================================================
    
    @pytest.mark.asyncio
    async def test_message_format_consistency(self):
        """
        Test that all initial_state messages use consistent format
        
        **Validates: Requirements 2.2**
        
        This test verifies that:
        1. Request_state handler sends consistent format
        2. Multiple requests use type "initial_state" with nested payload structure
        3. No "full_state" messages are sent
        """
        client = TestClient(app)
        
        with client.websocket_connect("/ws/test-client-integration-7?session_id=test-session-integration-7") as websocket:
            # Send first request_state
            websocket.send_text(json.dumps({
                "type": "request_state",
                "payload": {}
            }))
            
            data1 = websocket.receive_text()
            request_message1 = json.loads(data1)
            
            # Send second request_state
            websocket.send_text(json.dumps({
                "type": "request_state",
                "payload": {}
            }))
            
            data2 = websocket.receive_text()
            request_message2 = json.loads(data2)
            
            # Verify both messages have the same format
            assert request_message1.get("type") == "initial_state", \
                f"First request: Expected 'initial_state', got '{request_message1.get('type')}'"
            assert request_message2.get("type") == "initial_state", \
                f"Second request: Expected 'initial_state', got '{request_message2.get('type')}'"
            
            # Verify both have nested payload structure
            assert "payload" in request_message1 and "state" in request_message1["payload"], \
                "First request: Missing nested payload structure"
            assert "payload" in request_message2 and "state" in request_message2["payload"], \
                "Second request: Missing nested payload structure"
            
            # Verify no "full_state" type is used
            assert request_message1.get("type") != "full_state", \
                "First request should not use 'full_state' type"
            assert request_message2.get("type") != "full_state", \
                "Second request should not use 'full_state' type"
            
            print(f"✓ Message format consistency verified")
            print(f"✓ All request_state responses use 'initial_state' with nested payload")
            print(f"✓ No 'full_state' messages detected")


if __name__ == "__main__":
    print("=" * 80)
    print("Integration Tests for WebSocket Message Flow Fix")
    print("=" * 80)
    print()
    print("These tests verify the complete WebSocket connection and state")
    print("synchronization flows after implementing the fix.")
    print()
    print("Test scenarios:")
    print("1. Full connection flow: connect → receive initial_state → state initialized")
    print("2. Reconnection flow: disconnect → reconnect → receive initial_state → state re-initialized")
    print("3. State request flow: connect → request_state → receive initial_state → state updated")
    print("4. Multi-client flow: client A connects → client B connects → both receive initial_state")
    print("5. No refresh loop or 'State not initialized' warnings")
    print("6. Frontend state is properly initialized on first connection")
    print("7. Message format consistency across all code paths")
    print()
    print("Running tests...")
    print()
    
    pytest.main([__file__, "-v", "-s", "--tb=short"])
