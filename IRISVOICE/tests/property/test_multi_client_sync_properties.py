"""
Property-based tests for multi-client state synchronization.
Tests that field updates are broadcast to all clients in the same session.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from hypothesis import given, settings, strategies as st, seed
import sys
import os

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.ws_manager import WebSocketManager
from backend.sessions.session_manager import SessionManager
from backend.state_manager import StateManager


# ============================================================================
# Test Data Generators (Hypothesis Strategies)
# ============================================================================

@st.composite
def client_ids(draw):
    """Generate valid client IDs."""
    return draw(st.one_of(
        st.uuids().map(str),
        st.text(alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd')), min_size=5, max_size=50)
    ))


@st.composite
def subnode_ids(draw):
    """Generate valid subnode IDs."""
    return draw(st.sampled_from([
        "input", "output", "processing", "audio_model",
        "identity", "wake", "speech", "memory",
        "tools", "vision", "workflows", "favorites", "shortcuts", "gui",
        "power", "display", "storage", "network",
        "theme", "startup", "behavior", "notifications",
        "analytics", "logs", "diagnostics", "updates"
    ]))


@st.composite
def field_ids(draw):
    """Generate valid field IDs."""
    return draw(st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'), whitelist_characters='_'),
        min_size=1,
        max_size=30
    ))


@st.composite
def field_values(draw):
    """Generate valid field values (string, number, or boolean)."""
    return draw(st.one_of(
        st.text(min_size=0, max_size=100),
        st.integers(min_value=-1000, max_value=1000),
        st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        st.booleans()
    ))


# ============================================================================
# Property 6: Multi-Client State Synchronization
# Feature: irisvoice-backend-integration, Property 6: Multi-Client State Synchronization
# Validates: Requirements 2.6, 6.7, 21.1-21.3
# ============================================================================

class TestMultiClientStateSynchronization:
    """
    Property 6: Multi-Client State Synchronization
    
    For any field update in a session with multiple connected clients, all 
    clients in that session shall receive a field_updated message with the 
    new value.
    """
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        num_clients=st.integers(min_value=2, max_value=5),
        subnode_id=subnode_ids(),
        field_id=field_ids(),
        value=field_values()
    )
    async def test_field_update_broadcasts_to_all_clients(
        self, num_clients, subnode_id, field_id, value
    ):
        """
        Property: For any field update in a session with multiple clients, 
        all clients receive a field_updated message.
        
        # Feature: irisvoice-backend-integration, Property 6: Multi-Client State Synchronization
        """
        # Create session manager, state manager, and websocket manager
        session_manager = SessionManager()
        state_manager = StateManager(session_manager=session_manager)
        ws_manager = WebSocketManager(
            session_manager=session_manager,
            state_manager=state_manager
        )
        
        await session_manager.start()
        
        try:
            # Create a single session
            session_id = await session_manager.create_session()
            
            # Connect multiple clients to the same session
            client_ids_list = [f"client-{i}" for i in range(num_clients)]
            mock_websockets = {}
            
            for client_id in client_ids_list:
                mock_websocket = AsyncMock()
                mock_websocket.accept = AsyncMock()
                mock_websocket.send_json = AsyncMock()
                mock_websockets[client_id] = mock_websocket
                
                # Connect client to the session
                result_session_id = await ws_manager.connect(
                    mock_websocket, client_id, session_id
                )
                assert result_session_id == session_id
            
            # Verify all clients are in the same session
            session = session_manager.get_session(session_id)
            assert session is not None
            assert len(session.connected_clients) == num_clients
            
            # Update a field value
            success, _ = await state_manager.update_field(
                session_id, subnode_id, field_id, value
            )
            assert success, "Field update should succeed"
            
            # Broadcast field_updated message to all clients in the session
            field_updated_message = {
                "type": "field_updated",
                "payload": {
                    "subnode_id": subnode_id,
                    "field_id": field_id,
                    "value": value,
                    "valid": True
                }
            }
            
            await ws_manager.broadcast_to_session(session_id, field_updated_message)
            
            # Give a moment for async operations to complete
            await asyncio.sleep(0.1)
            
            # Verify all clients received the field_updated message
            for client_id in client_ids_list:
                mock_websocket = mock_websockets[client_id]
                # Check that send_json was called at least once
                assert mock_websocket.send_json.called, \
                    f"Client {client_id} should have received a message"
                
                # Check if any of the calls contained the field_updated message
                calls = mock_websocket.send_json.call_args_list
                field_updated_received = any(
                    call[0][0].get("type") == "field_updated" and
                    call[0][0].get("payload", {}).get("subnode_id") == subnode_id and
                    call[0][0].get("payload", {}).get("field_id") == field_id and
                    call[0][0].get("payload", {}).get("value") == value
                    for call in calls
                )
                
                assert field_updated_received, \
                    f"Client {client_id} should have received field_updated message"
        
        finally:
            # Cleanup
            for client_id in client_ids_list:
                ws_manager.disconnect(client_id)
            await session_manager.stop()
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        num_clients=st.integers(min_value=2, max_value=5),
        subnode_id=subnode_ids(),
        field_id=field_ids(),
        value=field_values()
    )
    async def test_field_update_excludes_sender_client(
        self, num_clients, subnode_id, field_id, value
    ):
        """
        Property: For any field update, the sender client can be excluded 
        from the broadcast (optimistic update pattern).
        
        # Feature: irisvoice-backend-integration, Property 6: Multi-Client State Synchronization
        """
        # Create session manager, state manager, and websocket manager
        session_manager = SessionManager()
        state_manager = StateManager(session_manager=session_manager)
        ws_manager = WebSocketManager(
            session_manager=session_manager,
            state_manager=state_manager
        )
        
        await session_manager.start()
        
        try:
            # Create a single session
            session_id = await session_manager.create_session()
            
            # Connect multiple clients to the same session
            client_ids_list = [f"client-{i}" for i in range(num_clients)]
            mock_websockets = {}
            
            for client_id in client_ids_list:
                mock_websocket = AsyncMock()
                mock_websocket.accept = AsyncMock()
                mock_websocket.send_json = AsyncMock()
                mock_websockets[client_id] = mock_websocket
                
                await ws_manager.connect(mock_websocket, client_id, session_id)
            
            # Choose first client as the sender
            sender_client_id = client_ids_list[0]
            
            # Update a field value
            success, _ = await state_manager.update_field(
                session_id, subnode_id, field_id, value
            )
            assert success
            
            # Broadcast field_updated message, excluding the sender
            field_updated_message = {
                "type": "field_updated",
                "payload": {
                    "subnode_id": subnode_id,
                    "field_id": field_id,
                    "value": value,
                    "valid": True
                }
            }
            
            await ws_manager.broadcast_to_session(
                session_id, 
                field_updated_message,
                exclude_clients={sender_client_id}
            )
            
            # Give a moment for async operations to complete
            await asyncio.sleep(0.1)
            
            # Verify sender did NOT receive the message
            sender_websocket = mock_websockets[sender_client_id]
            if sender_websocket.send_json.called:
                calls = sender_websocket.send_json.call_args_list
                field_updated_received = any(
                    call[0][0].get("type") == "field_updated" and
                    call[0][0].get("payload", {}).get("subnode_id") == subnode_id and
                    call[0][0].get("payload", {}).get("field_id") == field_id
                    for call in calls
                )
                assert not field_updated_received, \
                    "Sender client should NOT have received field_updated message"
            
            # Verify other clients DID receive the message
            for client_id in client_ids_list[1:]:
                mock_websocket = mock_websockets[client_id]
                assert mock_websocket.send_json.called, \
                    f"Client {client_id} should have received a message"
                
                calls = mock_websocket.send_json.call_args_list
                field_updated_received = any(
                    call[0][0].get("type") == "field_updated" and
                    call[0][0].get("payload", {}).get("subnode_id") == subnode_id and
                    call[0][0].get("payload", {}).get("field_id") == field_id and
                    call[0][0].get("payload", {}).get("value") == value
                    for call in calls
                )
                
                assert field_updated_received, \
                    f"Client {client_id} should have received field_updated message"
        
        finally:
            # Cleanup
            for client_id in client_ids_list:
                ws_manager.disconnect(client_id)
            await session_manager.stop()
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        num_clients_session1=st.integers(min_value=2, max_value=3),
        num_clients_session2=st.integers(min_value=2, max_value=3),
        subnode_id=subnode_ids(),
        field_id=field_ids(),
        value=field_values()
    )
    async def test_field_update_only_broadcasts_to_same_session(
        self, num_clients_session1, num_clients_session2, subnode_id, field_id, value
    ):
        """
        Property: For any field update in a session, only clients in that 
        session receive the update, not clients in other sessions.
        
        # Feature: irisvoice-backend-integration, Property 6: Multi-Client State Synchronization
        """
        # Create session manager, state manager, and websocket manager
        session_manager = SessionManager()
        state_manager = StateManager(session_manager=session_manager)
        ws_manager = WebSocketManager(
            session_manager=session_manager,
            state_manager=state_manager
        )
        
        await session_manager.start()
        
        try:
            # Create two separate sessions
            session_id1 = await session_manager.create_session()
            session_id2 = await session_manager.create_session()
            
            # Connect clients to session 1
            session1_clients = [f"s1-client-{i}" for i in range(num_clients_session1)]
            session1_websockets = {}
            
            for client_id in session1_clients:
                mock_websocket = AsyncMock()
                mock_websocket.accept = AsyncMock()
                mock_websocket.send_json = AsyncMock()
                session1_websockets[client_id] = mock_websocket
                
                await ws_manager.connect(mock_websocket, client_id, session_id1)
            
            # Connect clients to session 2
            session2_clients = [f"s2-client-{i}" for i in range(num_clients_session2)]
            session2_websockets = {}
            
            for client_id in session2_clients:
                mock_websocket = AsyncMock()
                mock_websocket.accept = AsyncMock()
                mock_websocket.send_json = AsyncMock()
                session2_websockets[client_id] = mock_websocket
                
                await ws_manager.connect(mock_websocket, client_id, session_id2)
            
            # Update a field value in session 1
            success, _ = await state_manager.update_field(
                session_id1, subnode_id, field_id, value
            )
            assert success
            
            # Broadcast field_updated message to session 1 only
            field_updated_message = {
                "type": "field_updated",
                "payload": {
                    "subnode_id": subnode_id,
                    "field_id": field_id,
                    "value": value,
                    "valid": True
                }
            }
            
            await ws_manager.broadcast_to_session(session_id1, field_updated_message)
            
            # Give a moment for async operations to complete
            await asyncio.sleep(0.1)
            
            # Verify session 1 clients received the message
            for client_id in session1_clients:
                mock_websocket = session1_websockets[client_id]
                assert mock_websocket.send_json.called, \
                    f"Session 1 client {client_id} should have received a message"
                
                calls = mock_websocket.send_json.call_args_list
                field_updated_received = any(
                    call[0][0].get("type") == "field_updated" and
                    call[0][0].get("payload", {}).get("subnode_id") == subnode_id and
                    call[0][0].get("payload", {}).get("field_id") == field_id and
                    call[0][0].get("payload", {}).get("value") == value
                    for call in calls
                )
                
                assert field_updated_received, \
                    f"Session 1 client {client_id} should have received field_updated message"
            
            # Verify session 2 clients did NOT receive the message
            for client_id in session2_clients:
                mock_websocket = session2_websockets[client_id]
                
                if mock_websocket.send_json.called:
                    calls = mock_websocket.send_json.call_args_list
                    field_updated_received = any(
                        call[0][0].get("type") == "field_updated" and
                        call[0][0].get("payload", {}).get("subnode_id") == subnode_id and
                        call[0][0].get("payload", {}).get("field_id") == field_id
                        for call in calls
                    )
                    
                    assert not field_updated_received, \
                        f"Session 2 client {client_id} should NOT have received field_updated message"
        
        finally:
            # Cleanup
            for client_id in session1_clients + session2_clients:
                ws_manager.disconnect(client_id)
            await session_manager.stop()
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        num_clients=st.integers(min_value=2, max_value=5),
        field_updates=st.lists(
            st.tuples(subnode_ids(), field_ids(), field_values()),
            min_size=1,
            max_size=5
        )
    )
    async def test_multiple_field_updates_broadcast_to_all_clients(
        self, num_clients, field_updates
    ):
        """
        Property: For any sequence of field updates in a session, all clients 
        receive all field_updated messages.
        
        # Feature: irisvoice-backend-integration, Property 6: Multi-Client State Synchronization
        """
        # Create session manager, state manager, and websocket manager
        session_manager = SessionManager()
        state_manager = StateManager(session_manager=session_manager)
        ws_manager = WebSocketManager(
            session_manager=session_manager,
            state_manager=state_manager
        )
        
        await session_manager.start()
        
        try:
            # Create a single session
            session_id = await session_manager.create_session()
            
            # Connect multiple clients to the same session
            client_ids_list = [f"client-{i}" for i in range(num_clients)]
            mock_websockets = {}
            
            for client_id in client_ids_list:
                mock_websocket = AsyncMock()
                mock_websocket.accept = AsyncMock()
                mock_websocket.send_json = AsyncMock()
                mock_websockets[client_id] = mock_websocket
                
                await ws_manager.connect(mock_websocket, client_id, session_id)
            
            # Perform multiple field updates
            for subnode_id, field_id, value in field_updates:
                success, _ = await state_manager.update_field(
                    session_id, subnode_id, field_id, value
                )
                assert success
                
                # Broadcast field_updated message
                field_updated_message = {
                    "type": "field_updated",
                    "payload": {
                        "subnode_id": subnode_id,
                        "field_id": field_id,
                        "value": value,
                        "valid": True
                    }
                }
                
                await ws_manager.broadcast_to_session(session_id, field_updated_message)
            
            # Give a moment for async operations to complete
            await asyncio.sleep(0.1)
            
            # Verify all clients received all field_updated messages
            for client_id in client_ids_list:
                mock_websocket = mock_websockets[client_id]
                assert mock_websocket.send_json.called, \
                    f"Client {client_id} should have received messages"
                
                calls = mock_websocket.send_json.call_args_list
                
                # Check that each field update was received
                for subnode_id, field_id, value in field_updates:
                    field_updated_received = any(
                        call[0][0].get("type") == "field_updated" and
                        call[0][0].get("payload", {}).get("subnode_id") == subnode_id and
                        call[0][0].get("payload", {}).get("field_id") == field_id and
                        call[0][0].get("payload", {}).get("value") == value
                        for call in calls
                    )
                    
                    assert field_updated_received, \
                        f"Client {client_id} should have received update for {subnode_id}.{field_id}"
        
        finally:
            # Cleanup
            for client_id in client_ids_list:
                ws_manager.disconnect(client_id)
            await session_manager.stop()
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        num_initial_clients=st.integers(min_value=2, max_value=3),
        subnode_id=subnode_ids(),
        field_id=field_ids(),
        value=field_values()
    )
    async def test_new_client_does_not_receive_past_updates(
        self, num_initial_clients, subnode_id, field_id, value
    ):
        """
        Property: For any client that connects after a field update, it does 
        not receive the past update message (only current state on connection).
        
        # Feature: irisvoice-backend-integration, Property 6: Multi-Client State Synchronization
        """
        # Create session manager, state manager, and websocket manager
        session_manager = SessionManager()
        state_manager = StateManager(session_manager=session_manager)
        ws_manager = WebSocketManager(
            session_manager=session_manager,
            state_manager=state_manager
        )
        
        await session_manager.start()
        
        try:
            # Create a single session
            session_id = await session_manager.create_session()
            
            # Connect initial clients
            initial_clients = [f"initial-client-{i}" for i in range(num_initial_clients)]
            initial_websockets = {}
            
            for client_id in initial_clients:
                mock_websocket = AsyncMock()
                mock_websocket.accept = AsyncMock()
                mock_websocket.send_json = AsyncMock()
                initial_websockets[client_id] = mock_websocket
                
                await ws_manager.connect(mock_websocket, client_id, session_id)
            
            # Update a field value
            success, _ = await state_manager.update_field(
                session_id, subnode_id, field_id, value
            )
            assert success
            
            # Broadcast field_updated message to initial clients
            field_updated_message = {
                "type": "field_updated",
                "payload": {
                    "subnode_id": subnode_id,
                    "field_id": field_id,
                    "value": value,
                    "valid": True
                }
            }
            
            await ws_manager.broadcast_to_session(session_id, field_updated_message)
            
            # Give a moment for async operations to complete
            await asyncio.sleep(0.1)
            
            # Now connect a new client
            new_client_id = "new-client"
            new_websocket = AsyncMock()
            new_websocket.accept = AsyncMock()
            new_websocket.send_json = AsyncMock()
            
            await ws_manager.connect(new_websocket, new_client_id, session_id)
            
            # Give a moment for connection to complete
            await asyncio.sleep(0.1)
            
            # Verify new client did NOT receive the past field_updated message
            # (it should receive initial_state instead, but that's handled by gateway)
            if new_websocket.send_json.called:
                calls = new_websocket.send_json.call_args_list
                field_updated_received = any(
                    call[0][0].get("type") == "field_updated" and
                    call[0][0].get("payload", {}).get("subnode_id") == subnode_id and
                    call[0][0].get("payload", {}).get("field_id") == field_id
                    for call in calls
                )
                
                assert not field_updated_received, \
                    "New client should NOT receive past field_updated messages"
            
            # Verify the new client can retrieve the current value from state
            retrieved_value = await state_manager.get_field_value(
                session_id, subnode_id, field_id
            )
            assert retrieved_value == value, \
                "New client should be able to retrieve current field value from state"
        
        finally:
            # Cleanup
            for client_id in initial_clients + [new_client_id]:
                ws_manager.disconnect(client_id)
            await session_manager.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
