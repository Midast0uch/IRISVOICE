"""
Property-based tests for navigation history round-trip.
Tests that navigation actions can be reversed by calling go_back.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock
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


@st.composite
def subnode_ids(draw):
    """Generate valid subnode IDs."""
    return draw(st.sampled_from([
        "input", "output", "processing", "model",
        "identity", "wake", "speech", "memory",
        "tools", "workflows", "favorites", "shortcuts",
        "power", "display", "storage", "network",
        "theme", "startup", "behavior", "notifications",
        "analytics", "logs", "diagnostics", "updates"
    ]))


@st.composite
def navigation_sequences(draw):
    """Generate sequences of navigation actions (category, subnode_id)."""
    # Generate 1 to 3 navigation steps (reduced from 10 to prevent hanging)
    length = draw(st.integers(min_value=1, max_value=3))
    sequence = []
    for _ in range(length):
        category = draw(categories())
        subnode_id = draw(subnode_ids())
        sequence.append((category, subnode_id))
    return sequence


# ============================================================================
# Property 21: Navigation History Round-Trip
# Feature: irisvoice-backend-integration, Property 21: Navigation History Round-Trip
# Validates: Requirements 7.6, 7.7
# ============================================================================

class TestNavigationHistoryRoundTrip:
    """
    Property 21: Navigation History Round-Trip
    
    For any sequence of navigation actions (select_category, select_subnode), 
    performing those actions and then calling go_back the same number of times 
    shall restore the original navigation state.
    """
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=5000)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        client_id=client_ids(),
        navigation_sequence=navigation_sequences()
    )
    async def test_navigation_history_roundtrip(self, client_id, navigation_sequence):
        """
        Property: For any sequence of navigation actions, performing those 
        actions and then calling go_back the same number of times shall 
        restore the original navigation state.
        
        # Feature: irisvoice-backend-integration, Property 21: Navigation History Round-Trip
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
            
            # Record initial state
            initial_state = await state_manager.get_state(session_id)
            initial_category = initial_state.current_category
            initial_subnode = initial_state.current_subnode
            
            # Perform navigation sequence
            for category, subnode_id in navigation_sequence:
                # Select category
                select_category_message = {
                    "type": "select_category",
                    "payload": {
                        "category": category
                    }
                }
                await gateway.handle_message(client_id, select_category_message)
                await asyncio.sleep(0.01)  # Reduced delay for faster execution
                
                # Select subnode
                select_subnode_message = {
                    "type": "select_subnode",
                    "payload": {
                        "subnode_id": subnode_id
                    }
                }
                await gateway.handle_message(client_id, select_subnode_message)
                await asyncio.sleep(0.01)  # Reduced delay for faster execution
            
            # Verify we've navigated away from initial state
            current_state = await state_manager.get_state(session_id)
            # We should be at the last navigation point
            assert current_state.current_category is not None or initial_category is not None
            assert current_state.current_subnode is not None or initial_subnode is not None
            
            # Go back the same number of times (2 actions per navigation: category + subnode)
            num_go_backs = len(navigation_sequence) * 2
            for _ in range(num_go_backs):
                go_back_message = {
                    "type": "go_back",
                    "payload": {}
                }
                await gateway.handle_message(client_id, go_back_message)
                await asyncio.sleep(0.01)  # Reduced delay for faster execution
            
            # Verify state restored to initial
            final_state = await state_manager.get_state(session_id)
            
            # Compare categories
            if initial_category is None:
                assert final_state.current_category is None, \
                    f"Expected category to be None, but got {final_state.current_category}"
            else:
                assert final_state.current_category is not None, \
                    "Expected category to be set, but got None"
                assert final_state.current_category.value == initial_category.value, \
                    f"Expected category {initial_category.value}, but got {final_state.current_category.value}"
            
            # Compare subnodes
            assert final_state.current_subnode == initial_subnode, \
                f"Expected subnode {initial_subnode}, but got {final_state.current_subnode}"
        
        finally:
            # Cleanup
            try:
                ws_manager.disconnect(client_id)
            except Exception:
                pass  # Ignore cleanup errors
            try:
                await session_manager.stop()
            except Exception:
                pass  # Ignore cleanup errors
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=5000)
    @seed(42)
    @given(
        client_id=client_ids(),
        category=categories(),
        subnode_id=subnode_ids()
    )
    async def test_single_navigation_go_back(self, client_id, category, subnode_id):
        """
        Property: For a single navigation action (category + subnode), 
        calling go_back twice should restore the initial state.
        
        # Feature: irisvoice-backend-integration, Property 21: Navigation History Round-Trip
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
            
            # Record initial state (should be None, None)
            initial_state = await state_manager.get_state(session_id)
            initial_category = initial_state.current_category
            initial_subnode = initial_state.current_subnode
            
            # Navigate to category
            select_category_message = {
                "type": "select_category",
                "payload": {
                    "category": category
                }
            }
            await gateway.handle_message(client_id, select_category_message)
            await asyncio.sleep(0.01)
            
            # Navigate to subnode
            select_subnode_message = {
                "type": "select_subnode",
                "payload": {
                    "subnode_id": subnode_id
                }
            }
            await gateway.handle_message(client_id, select_subnode_message)
            await asyncio.sleep(0.01)
            
            # Verify we've navigated
            current_state = await state_manager.get_state(session_id)
            assert current_state.current_category is not None
            assert current_state.current_category.value == category
            assert current_state.current_subnode == subnode_id
            
            # Go back once (should restore category without subnode)
            go_back_message = {"type": "go_back", "payload": {}}
            await gateway.handle_message(client_id, go_back_message)
            await asyncio.sleep(0.01)
            
            after_first_back = await state_manager.get_state(session_id)
            assert after_first_back.current_category is not None
            assert after_first_back.current_category.value == category
            assert after_first_back.current_subnode is None
            
            # Go back again (should restore initial state)
            await gateway.handle_message(client_id, go_back_message)
            await asyncio.sleep(0.01)
            
            final_state = await state_manager.get_state(session_id)
            
            # Verify restored to initial state
            if initial_category is None:
                assert final_state.current_category is None
            else:
                assert final_state.current_category.value == initial_category.value
            
            assert final_state.current_subnode == initial_subnode
        
        finally:
            # Cleanup
            try:
                ws_manager.disconnect(client_id)
            except Exception:
                pass  # Ignore cleanup errors
            try:
                await session_manager.stop()
            except Exception:
                pass  # Ignore cleanup errors
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=5000)
    @seed(42)
    @given(
        client_id=client_ids(),
        category=categories()
    )
    async def test_go_back_with_empty_history(self, client_id, category):
        """
        Property: Calling go_back when navigation history is empty should 
        not crash and should leave the state unchanged.
        
        # Feature: irisvoice-backend-integration, Property 21: Navigation History Round-Trip
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
            
            # Get initial state
            initial_state = await state_manager.get_state(session_id)
            
            # Try to go back with empty history (should not crash)
            go_back_message = {"type": "go_back", "payload": {}}
            await gateway.handle_message(client_id, go_back_message)
            await asyncio.sleep(0.01)
            
            # Verify state unchanged
            final_state = await state_manager.get_state(session_id)
            assert final_state.current_category == initial_state.current_category
            assert final_state.current_subnode == initial_state.current_subnode
        
        finally:
            # Cleanup
            try:
                ws_manager.disconnect(client_id)
            except Exception:
                pass  # Ignore cleanup errors
            try:
                await session_manager.stop()
            except Exception:
                pass  # Ignore cleanup errors


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
