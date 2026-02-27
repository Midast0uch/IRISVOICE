"""
Property-based tests for category navigation.
Tests that category selection updates state correctly and returns appropriate subnodes.
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
from backend.iris_gateway import IRISGateway
from backend.core_models import Category


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
def categories(draw):
    """Generate valid category values."""
    return draw(st.sampled_from([
        "voice", "agent", "automate", "system", "customize", "monitor"
    ]))


# ============================================================================
# Property 19: Category Navigation
# Feature: irisvoice-backend-integration, Property 19: Category Navigation
# Validates: Requirements 7.1, 7.2, 7.3
# ============================================================================

class TestCategoryNavigation:
    """
    Property 19: Category Navigation
    
    For any select_category message, the State_Manager shall update 
    current_category, send a category_changed message, and include all 
    subnodes for that category.
    """
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        client_id=client_ids(),
        category=categories()
    )
    async def test_category_selection_updates_state(self, client_id, category):
        """
        Property: For any select_category message, the current_category 
        is updated in the state.
        
        # Feature: irisvoice-backend-integration, Property 19: Category Navigation
        """
        # Create session manager, state manager, websocket manager, and gateway
        session_manager = SessionManager()
        state_manager = StateManager(session_manager=session_manager)
        ws_manager = WebSocketManager(
            session_manager=session_manager,
            state_manager=state_manager
        )
        gateway = IRISGateway(
            ws_manager=ws_manager,
            state_manager=state_manager
        )
        
        await session_manager.start()
        
        try:
            # Create a session
            session_id = await session_manager.create_session()
            
            # Connect client to the session
            mock_websocket = AsyncMock()
            mock_websocket.accept = AsyncMock()
            mock_websocket.send_json = AsyncMock()
            
            result_session_id = await ws_manager.connect(
                mock_websocket, client_id, session_id
            )
            assert result_session_id == session_id
            
            # Send select_category message
            select_category_message = {
                "type": "select_category",
                "payload": {
                    "category": category
                }
            }
            
            await gateway.handle_message(client_id, select_category_message)
            
            # Give a moment for async operations to complete
            await asyncio.sleep(0.1)
            
            # Verify state was updated
            state = await state_manager.get_state(session_id)
            assert state is not None, "State should exist"
            assert state.current_category is not None, "Current category should be set"
            assert state.current_category.value == category, \
                f"Current category should be {category}, but got {state.current_category.value}"
        
        finally:
            # Cleanup
            ws_manager.disconnect(client_id)
            await session_manager.stop()
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        client_id=client_ids(),
        category=categories()
    )
    async def test_category_selection_sends_category_changed_message(
        self, client_id, category
    ):
        """
        Property: For any select_category message, a category_changed 
        message is sent to the client.
        
        # Feature: irisvoice-backend-integration, Property 19: Category Navigation
        """
        # Create session manager, state manager, websocket manager, and gateway
        session_manager = SessionManager()
        state_manager = StateManager(session_manager=session_manager)
        ws_manager = WebSocketManager(
            session_manager=session_manager,
            state_manager=state_manager
        )
        gateway = IRISGateway(
            ws_manager=ws_manager,
            state_manager=state_manager
        )
        
        await session_manager.start()
        
        try:
            # Create a session
            session_id = await session_manager.create_session()
            
            # Connect client to the session
            mock_websocket = AsyncMock()
            mock_websocket.accept = AsyncMock()
            mock_websocket.send_json = AsyncMock()
            
            await ws_manager.connect(mock_websocket, client_id, session_id)
            
            # Send select_category message
            select_category_message = {
                "type": "select_category",
                "payload": {
                    "category": category
                }
            }
            
            await gateway.handle_message(client_id, select_category_message)
            
            # Give a moment for async operations to complete
            await asyncio.sleep(0.1)
            
            # Verify category_changed message was sent
            assert mock_websocket.send_json.called, \
                "Client should have received a message"
            
            calls = mock_websocket.send_json.call_args_list
            category_changed_received = any(
                call[0][0].get("type") == "category_changed" and
                call[0][0].get("payload", {}).get("category") == category
                for call in calls
            )
            
            assert category_changed_received, \
                f"Client should have received category_changed message for {category}"
        
        finally:
            # Cleanup
            ws_manager.disconnect(client_id)
            await session_manager.stop()
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        client_id=client_ids(),
        category=categories()
    )
    async def test_category_selection_includes_subnodes(self, client_id, category):
        """
        Property: For any select_category message, the category_changed 
        message includes all subnodes for that category.
        
        # Feature: irisvoice-backend-integration, Property 19: Category Navigation
        """
        # Create session manager, state manager, websocket manager, and gateway
        session_manager = SessionManager()
        state_manager = StateManager(session_manager=session_manager)
        ws_manager = WebSocketManager(
            session_manager=session_manager,
            state_manager=state_manager
        )
        gateway = IRISGateway(
            ws_manager=ws_manager,
            state_manager=state_manager
        )
        
        await session_manager.start()
        
        try:
            # Create a session
            session_id = await session_manager.create_session()
            
            # Connect client to the session
            mock_websocket = AsyncMock()
            mock_websocket.accept = AsyncMock()
            mock_websocket.send_json = AsyncMock()
            
            await ws_manager.connect(mock_websocket, client_id, session_id)
            
            # Send select_category message
            select_category_message = {
                "type": "select_category",
                "payload": {
                    "category": category
                }
            }
            
            await gateway.handle_message(client_id, select_category_message)
            
            # Give a moment for async operations to complete
            await asyncio.sleep(0.1)
            
            # Verify category_changed message includes subnodes
            assert mock_websocket.send_json.called, \
                "Client should have received a message"
            
            calls = mock_websocket.send_json.call_args_list
            
            # Find the category_changed message
            category_changed_message = None
            for call in calls:
                msg = call[0][0]
                if (msg.get("type") == "category_changed" and 
                    msg.get("payload", {}).get("category") == category):
                    category_changed_message = msg
                    break
            
            assert category_changed_message is not None, \
                f"Should have received category_changed message for {category}"
            
            # Verify subnodes are included
            subnodes = category_changed_message.get("payload", {}).get("subnodes")
            assert subnodes is not None, "Subnodes should be included in the message"
            assert isinstance(subnodes, list), "Subnodes should be a list"
            
            # Verify subnodes are not empty (each category should have subnodes)
            assert len(subnodes) > 0, \
                f"Category {category} should have at least one subnode"
            
            # Verify each subnode has required fields
            for subnode in subnodes:
                assert "id" in subnode, "Subnode should have an id"
                assert "label" in subnode, "Subnode should have a label"
                assert "icon" in subnode, "Subnode should have an icon"
                assert "fields" in subnode, "Subnode should have fields"
        
        finally:
            # Cleanup
            ws_manager.disconnect(client_id)
            await session_manager.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
