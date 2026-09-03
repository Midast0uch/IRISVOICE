"""
Bug Condition Exploration Test for WebSocket Message Flow Fix

**Validates: Requirements 2.1, 2.2, 2.3**

This test is designed to FAIL on unfixed code to confirm the bug exists.
The bug manifests as a message type and payload structure mismatch where:
- main.py sends {"type": "full_state", "state": {...}} (flat structure)
- Frontend expects {"type": "initial_state", "payload": {"state": {...}}} (nested structure)

CRITICAL: This test MUST FAIL on unfixed code - failure confirms the bug exists.
DO NOT attempt to fix the test or the code when it fails.

This test encodes the expected behavior - it will validate the fix when it passes after implementation.

GOAL: Surface counterexamples that demonstrate the bug exists.
"""

import pytest
import asyncio
import json
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocket
from unittest.mock import Mock, AsyncMock, patch
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from backend.main import app
from backend.models import IRISState, Category


class TestWebSocketMessageFlowBugExploration:
    """
    Property 1: Fault Condition - Initial State Message Format Mismatch
    
    This test explores the bug condition by testing both code paths that send initial state:
    1. websocket_endpoint (on connection)
    2. handle_message (on request_state)
    
    Expected to FAIL on unfixed code, demonstrating:
    - main.py sends {"type": "full_state", "state": {...}} instead of expected format
    - Frontend expects {"type": "initial_state", "payload": {"state": {...}}}
    """
    
    @pytest.mark.asyncio
    async def test_websocket_connection_sends_correct_initial_state_format(self):
        """
        Test that websocket_endpoint sends initial state with correct message format.
        
        Expected behavior (from design):
        - Message type should be "initial_state"
        - Payload structure should be {"type": "initial_state", "payload": {"state": {...}}}
        
        Current buggy behavior (will cause test to FAIL):
        - Message type is "full_state"
        - Payload structure is {"type": "full_state", "state": {...}}
        
        This test will FAIL on unfixed code, proving the bug exists.
        """
        client = TestClient(app)
        
        with client.websocket_connect("/ws/test-client-1?session_id=test-session") as websocket:
            # Receive the initial state message sent on connection
            data = websocket.receive_text()
            message = json.loads(data)
            
            # EXPECTED BEHAVIOR: Message should have type "initial_state"
            assert message.get("type") == "initial_state", \
                f"Expected message type 'initial_state', but got '{message.get('type')}'. " \
                f"Bug confirmed: main.py sends 'full_state' instead of 'initial_state'"
            
            # EXPECTED BEHAVIOR: Message should have nested payload structure
            assert "payload" in message, \
                f"Expected 'payload' key in message, but got keys: {list(message.keys())}. " \
                f"Bug confirmed: main.py uses flat structure with 'state' key instead of nested 'payload'"
            
            # EXPECTED BEHAVIOR: State data should be nested under payload.state
            assert "state" in message.get("payload", {}), \
                f"Expected 'state' key under 'payload', but payload contains: {list(message.get('payload', {}).keys())}. " \
                f"Bug confirmed: main.py sends state at root level instead of nested under payload"
            
            # Verify the complete expected structure
            assert message.get("type") == "initial_state" and \
                   "payload" in message and \
                   "state" in message["payload"], \
                f"Expected structure: {{'type': 'initial_state', 'payload': {{'state': {{...}}}}}}. " \
                f"Got: {{'type': '{message.get('type')}', keys: {list(message.keys())}}}. " \
                f"Bug confirmed: Message format mismatch between backend and frontend expectations"
    
    @pytest.mark.asyncio
    async def test_request_state_message_sends_correct_format(self):
        """
        Test that handle_message request_state handler sends correct message format.
        
        Expected behavior (from design):
        - Message type should be "initial_state"
        - Payload structure should be {"type": "initial_state", "payload": {"state": {...}}}
        
        Current buggy behavior (will cause test to FAIL):
        - Message type is "full_state"
        - Payload structure is {"type": "full_state", "state": {...}}
        
        This test will FAIL on unfixed code, proving the bug exists.
        """
        client = TestClient(app)
        
        with client.websocket_connect("/ws/test-client-2?session_id=test-session-2") as websocket:
            # Receive and discard the initial connection message
            _ = websocket.receive_text()
            
            # Send request_state message
            websocket.send_text(json.dumps({
                "type": "request_state",
                "payload": {}
            }))
            
            # Receive the response
            data = websocket.receive_text()
            message = json.loads(data)
            
            # EXPECTED BEHAVIOR: Message should have type "initial_state"
            assert message.get("type") == "initial_state", \
                f"Expected message type 'initial_state', but got '{message.get('type')}'. " \
                f"Bug confirmed: handle_message sends 'full_state' instead of 'initial_state'"
            
            # EXPECTED BEHAVIOR: Message should have nested payload structure
            assert "payload" in message, \
                f"Expected 'payload' key in message, but got keys: {list(message.keys())}. " \
                f"Bug confirmed: handle_message uses flat structure with 'state' key instead of nested 'payload'"
            
            # EXPECTED BEHAVIOR: State data should be nested under payload.state
            assert "state" in message.get("payload", {}), \
                f"Expected 'state' key under 'payload', but payload contains: {list(message.get('payload', {}).keys())}. " \
                f"Bug confirmed: handle_message sends state at root level instead of nested under payload"
            
            # Verify the complete expected structure
            assert message.get("type") == "initial_state" and \
                   "payload" in message and \
                   "state" in message["payload"], \
                f"Expected structure: {{'type': 'initial_state', 'payload': {{'state': {{...}}}}}}. " \
                f"Got: {{'type': '{message.get('type')}', keys: {list(message.keys())}}}. " \
                f"Bug confirmed: Message format mismatch between backend and frontend expectations"
    
    @pytest.mark.asyncio
    async def test_both_code_paths_use_consistent_message_format(self):
        """
        Test that both code paths (websocket_endpoint and handle_message) use the same message format.
        
        This test verifies consistency across both code paths that send initial state.
        
        Expected behavior (from design):
        - Both paths should send {"type": "initial_state", "payload": {"state": {...}}}
        
        Current buggy behavior (will cause test to FAIL):
        - Both paths send {"type": "full_state", "state": {...}}
        
        This test will FAIL on unfixed code, proving the bug exists.
        """
        client = TestClient(app)
        
        # Test first code path: websocket_endpoint (on connection)
        with client.websocket_connect("/ws/test-client-3?session_id=test-session-3") as websocket:
            data1 = websocket.receive_text()
            message1 = json.loads(data1)
            
            # Send request_state to test second code path
            websocket.send_text(json.dumps({
                "type": "request_state",
                "payload": {}
            }))
            
            data2 = websocket.receive_text()
            message2 = json.loads(data2)
            
            # Both messages should have the same structure
            assert message1.get("type") == message2.get("type") == "initial_state", \
                f"Expected both messages to have type 'initial_state', but got: " \
                f"connection='{message1.get('type')}', request_state='{message2.get('type')}'. " \
                f"Bug confirmed: Inconsistent message types across code paths"
            
            # Both should have nested payload structure
            assert "payload" in message1 and "payload" in message2, \
                f"Expected both messages to have 'payload' key. " \
                f"connection keys: {list(message1.keys())}, request_state keys: {list(message2.keys())}. " \
                f"Bug confirmed: Inconsistent payload structure across code paths"
            
            # Both should have state nested under payload
            assert "state" in message1.get("payload", {}) and "state" in message2.get("payload", {}), \
                f"Expected both messages to have 'state' under 'payload'. " \
                f"Bug confirmed: Inconsistent state nesting across code paths"


if __name__ == "__main__":
    print("=" * 80)
    print("Bug Condition Exploration Test for WebSocket Message Flow Fix")
    print("=" * 80)
    print()
    print("This test is designed to FAIL on unfixed code to confirm the bug exists.")
    print()
    print("Expected counterexamples (bugs to be found):")
    print("1. main.py sends {'type': 'full_state', 'state': {...}} instead of")
    print("   {'type': 'initial_state', 'payload': {'state': {...}}}")
    print("2. Frontend ignores 'full_state' messages, leaving state uninitialized")
    print()
    print("Running tests...")
    print()
    
    pytest.main([__file__, "-v", "-s"])
