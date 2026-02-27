"""
Property-based tests for session state isolation.
Tests that concurrent sessions maintain independent state.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from hypothesis import given, settings, strategies as st, seed
import sys
import os

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.sessions.session_manager import SessionManager
from backend.state_manager import StateManager


# ============================================================================
# Test Data Generators (Hypothesis Strategies)
# ============================================================================

@st.composite
def session_ids(draw):
    """Generate valid session IDs."""
    return draw(st.uuids().map(str))


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
# Property 5: Session State Isolation
# Feature: irisvoice-backend-integration, Property 5: Session State Isolation
# Validates: Requirements 2.4
# ============================================================================

class TestSessionStateIsolation:
    """
    Property 5: Session State Isolation
    
    For any two concurrent sessions, updating a field value in one session 
    shall not affect the field value in the other session.
    """
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        subnode_id=subnode_ids(),
        field_id=field_ids(),
        value1=field_values(),
        value2=field_values()
    )
    async def test_field_update_isolation_between_sessions(
        self, subnode_id, field_id, value1, value2
    ):
        """
        Property: For any two sessions, updating a field in session1 does not 
        affect the same field in session2.
        
        # Feature: irisvoice-backend-integration, Property 5: Session State Isolation
        """
        # Create session manager and state manager
        session_manager = SessionManager()
        state_manager = StateManager(session_manager=session_manager)
        
        await session_manager.start()
        
        try:
            # Create two separate sessions
            session_id1 = await session_manager.create_session()
            session_id2 = await session_manager.create_session()
            
            # Verify sessions are different
            assert session_id1 != session_id2, "Sessions should have unique IDs"
            
            # Initialize state for both sessions
            await state_manager.initialize_session_state(session_id1)
            await state_manager.initialize_session_state(session_id2)
            
            # Set initial value in session1
            success1, _ = await state_manager.update_field(
                session_id1, subnode_id, field_id, value1
            )
            assert success1, "Field update in session1 should succeed"
            
            # Set different value in session2
            success2, _ = await state_manager.update_field(
                session_id2, subnode_id, field_id, value2
            )
            assert success2, "Field update in session2 should succeed"
            
            # Verify session1 still has its original value
            retrieved_value1 = await state_manager.get_field_value(
                session_id1, subnode_id, field_id
            )
            assert retrieved_value1 == value1, \
                f"Session1 field value should be {value1}, but got {retrieved_value1}"
            
            # Verify session2 has its own value
            retrieved_value2 = await state_manager.get_field_value(
                session_id2, subnode_id, field_id
            )
            assert retrieved_value2 == value2, \
                f"Session2 field value should be {value2}, but got {retrieved_value2}"
            
            # Verify values are independent (if they were different to begin with)
            if value1 != value2:
                assert retrieved_value1 != retrieved_value2, \
                    "Sessions should maintain different values when set differently"
        
        finally:
            # Cleanup
            await session_manager.stop()
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        num_sessions=st.integers(min_value=2, max_value=5),
        subnode_id=subnode_ids(),
        field_id=field_ids(),
        values=st.lists(field_values(), min_size=2, max_size=5)
    )
    async def test_multiple_sessions_maintain_independent_state(
        self, num_sessions, subnode_id, field_id, values
    ):
        """
        Property: For any N concurrent sessions, each maintains independent 
        field values.
        
        # Feature: irisvoice-backend-integration, Property 5: Session State Isolation
        """
        # Ensure we have enough values for all sessions
        if len(values) < num_sessions:
            values = values * ((num_sessions // len(values)) + 1)
        values = values[:num_sessions]
        
        # Create session manager and state manager
        session_manager = SessionManager()
        state_manager = StateManager(session_manager=session_manager)
        
        await session_manager.start()
        
        try:
            # Create multiple sessions
            session_ids = []
            for _ in range(num_sessions):
                session_id = await session_manager.create_session()
                session_ids.append(session_id)
                await state_manager.initialize_session_state(session_id)
            
            # Verify all session IDs are unique
            assert len(session_ids) == len(set(session_ids)), \
                "All session IDs should be unique"
            
            # Set different values in each session
            for i, session_id in enumerate(session_ids):
                success, _ = await state_manager.update_field(
                    session_id, subnode_id, field_id, values[i]
                )
                assert success, f"Field update in session {i} should succeed"
            
            # Verify each session maintains its own value
            for i, session_id in enumerate(session_ids):
                retrieved_value = await state_manager.get_field_value(
                    session_id, subnode_id, field_id
                )
                assert retrieved_value == values[i], \
                    f"Session {i} should have value {values[i]}, but got {retrieved_value}"
        
        finally:
            # Cleanup
            await session_manager.stop()
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        subnode_id=subnode_ids(),
        field_id=field_ids(),
        initial_value=field_values(),
        update_value=field_values()
    )
    async def test_session_isolation_during_concurrent_updates(
        self, subnode_id, field_id, initial_value, update_value
    ):
        """
        Property: For any two sessions with concurrent field updates, each 
        session's updates do not interfere with the other.
        
        # Feature: irisvoice-backend-integration, Property 5: Session State Isolation
        """
        # Create session manager and state manager
        session_manager = SessionManager()
        state_manager = StateManager(session_manager=session_manager)
        
        await session_manager.start()
        
        try:
            # Create two sessions
            session_id1 = await session_manager.create_session()
            session_id2 = await session_manager.create_session()
            
            await state_manager.initialize_session_state(session_id1)
            await state_manager.initialize_session_state(session_id2)
            
            # Set initial value in both sessions
            await state_manager.update_field(
                session_id1, subnode_id, field_id, initial_value
            )
            await state_manager.update_field(
                session_id2, subnode_id, field_id, initial_value
            )
            
            # Perform concurrent update in session1
            async def update_session1():
                await state_manager.update_field(
                    session_id1, subnode_id, field_id, update_value
                )
            
            # Perform concurrent read in session2
            async def read_session2():
                # Small delay to ensure session1 update happens first
                await asyncio.sleep(0.01)
                return await state_manager.get_field_value(
                    session_id2, subnode_id, field_id
                )
            
            # Execute concurrently
            update_task = asyncio.create_task(update_session1())
            read_task = asyncio.create_task(read_session2())
            
            await update_task
            session2_value = await read_task
            
            # Verify session2 still has initial value (not affected by session1 update)
            assert session2_value == initial_value, \
                f"Session2 should still have {initial_value}, but got {session2_value}"
            
            # Verify session1 has the updated value
            session1_value = await state_manager.get_field_value(
                session_id1, subnode_id, field_id
            )
            assert session1_value == update_value, \
                f"Session1 should have {update_value}, but got {session1_value}"
        
        finally:
            # Cleanup
            await session_manager.stop()
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        subnode_id=subnode_ids(),
        field_updates=st.lists(
            st.tuples(field_ids(), field_values()),
            min_size=1,
            max_size=10
        )
    )
    async def test_multiple_field_updates_maintain_isolation(
        self, subnode_id, field_updates
    ):
        """
        Property: For any sequence of field updates in one session, another 
        session's fields remain unaffected.
        
        # Feature: irisvoice-backend-integration, Property 5: Session State Isolation
        """
        # Create session manager and state manager
        session_manager = SessionManager()
        state_manager = StateManager(session_manager=session_manager)
        
        await session_manager.start()
        
        try:
            # Create two sessions
            session_id1 = await session_manager.create_session()
            session_id2 = await session_manager.create_session()
            
            await state_manager.initialize_session_state(session_id1)
            await state_manager.initialize_session_state(session_id2)
            
            # Perform multiple field updates in session1
            for field_id, value in field_updates:
                await state_manager.update_field(
                    session_id1, subnode_id, field_id, value
                )
            
            # Verify session2 has no field values for this subnode
            # (or default values if any were set)
            for field_id, _ in field_updates:
                session2_value = await state_manager.get_field_value(
                    session_id2, subnode_id, field_id
                )
                # Session2 should have None (default) since we never set values there
                assert session2_value is None, \
                    f"Session2 field {field_id} should be None, but got {repr(session2_value)}"
            
            # Verify session1 has all the updated values
            for field_id, expected_value in field_updates:
                session1_value = await state_manager.get_field_value(
                    session_id1, subnode_id, field_id
                )
                # Use repr for better error messages with empty strings
                assert session1_value == expected_value, \
                    f"Session1 field {field_id} should be {repr(expected_value)}, but got {repr(session1_value)}"
        
        finally:
            # Cleanup
            await session_manager.stop()
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        subnode_id=subnode_ids(),
        field_id=field_ids(),
        value=field_values()
    )
    async def test_session_deletion_does_not_affect_other_sessions(
        self, subnode_id, field_id, value
    ):
        """
        Property: For any session that is deleted, other sessions' state 
        remains intact.
        
        # Feature: irisvoice-backend-integration, Property 5: Session State Isolation
        """
        # Create session manager and state manager
        session_manager = SessionManager()
        state_manager = StateManager(session_manager=session_manager)
        
        await session_manager.start()
        
        try:
            # Create two sessions
            session_id1 = await session_manager.create_session()
            session_id2 = await session_manager.create_session()
            
            await state_manager.initialize_session_state(session_id1)
            await state_manager.initialize_session_state(session_id2)
            
            # Set value in both sessions
            await state_manager.update_field(
                session_id1, subnode_id, field_id, value
            )
            await state_manager.update_field(
                session_id2, subnode_id, field_id, value
            )
            
            # Delete session1
            await session_manager.remove_session(session_id1)
            
            # Verify session2 still has its value
            session2_value = await state_manager.get_field_value(
                session_id2, subnode_id, field_id
            )
            assert session2_value == value, \
                f"Session2 should still have {value} after session1 deletion, but got {session2_value}"
            
            # Verify session1 is gone
            session1 = session_manager.get_session(session_id1)
            assert session1 is None, "Session1 should be deleted"
        
        finally:
            # Cleanup
            await session_manager.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
