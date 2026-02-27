"""
Property-based tests for field value persistence round-trip.
Tests that field values persist correctly to storage and can be restored.
"""
import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path
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
        st.floats(
            min_value=-1000.0, 
            max_value=1000.0, 
            allow_nan=False, 
            allow_infinity=False
        ),
        st.booleans()
    ))


# ============================================================================
# Property 4: Field Value Persistence Round-Trip
# Feature: irisvoice-backend-integration, Property 4: Field Value Persistence Round-Trip
# Validates: Requirements 2.2, 2.3, 20.1-20.10
# ============================================================================

class TestFieldValuePersistence:
    """
    Property 4: Field Value Persistence Round-Trip
    
    For any field value update that passes validation, persisting the value 
    to storage and then loading it back shall produce an equivalent value.
    """
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        subnode_id=subnode_ids(),
        field_id=field_ids(),
        value=field_values()
    )
    async def test_single_field_persistence_roundtrip(
        self, subnode_id, field_id, value
    ):
        """
        Property: For any field value update, persisting and loading back 
        produces an equivalent value.
        
        # Feature: irisvoice-backend-integration, Property 4: Field Value Persistence Round-Trip
        """
        # Create temporary directory for persistence
        temp_dir = Path(tempfile.mkdtemp())
        
        try:
            # Create session manager and state manager
            session_manager = SessionManager()
            state_manager = StateManager(session_manager=session_manager)
            
            await session_manager.start()
            
            # Create a session
            session_id = await session_manager.create_session()
            
            # Initialize state with persistence
            await state_manager.initialize_session_state(session_id, str(temp_dir))
            
            # Update field value
            success, _ = await state_manager.update_field(
                session_id, subnode_id, field_id, value
            )
            assert success, f"Field update should succeed for {subnode_id}.{field_id} = {repr(value)}"
            
            # Force save to disk
            await state_manager.cleanup_session_state(session_id)
            
            # Remove session from memory
            await session_manager.remove_session(session_id)
            
            # Create new session with same ID (simulating restart)
            new_session_id = await session_manager.create_session(session_id)
            
            # Initialize state (should load from persistence)
            await state_manager.initialize_session_state(new_session_id, str(temp_dir))
            
            # Retrieve the value
            retrieved_value = await state_manager.get_field_value(
                new_session_id, subnode_id, field_id
            )
            
            # Verify equivalence
            assert retrieved_value == value, \
                f"Persisted value should be {repr(value)}, but got {repr(retrieved_value)}"
            
            # Cleanup
            await session_manager.stop()
            
        finally:
            # Clean up temp directory
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        field_updates=st.lists(
            st.tuples(subnode_ids(), field_ids(), field_values()),
            min_size=1,
            max_size=20
        )
    )
    async def test_multiple_fields_persistence_roundtrip(self, field_updates):
        """
        Property: For any sequence of field updates, all values persist 
        correctly and can be restored.
        
        # Feature: irisvoice-backend-integration, Property 4: Field Value Persistence Round-Trip
        """
        # Create temporary directory for persistence
        temp_dir = Path(tempfile.mkdtemp())
        
        try:
            # Create session manager and state manager
            session_manager = SessionManager()
            state_manager = StateManager(session_manager=session_manager)
            
            await session_manager.start()
            
            # Create a session
            session_id = await session_manager.create_session()
            
            # Initialize state with persistence
            await state_manager.initialize_session_state(session_id, str(temp_dir))
            
            # Update all fields
            for subnode_id, field_id, value in field_updates:
                success, _ = await state_manager.update_field(
                    session_id, subnode_id, field_id, value
                )
                assert success, f"Field update should succeed for {subnode_id}.{field_id}"
            
            # Force save to disk
            await state_manager.cleanup_session_state(session_id)
            
            # Remove session from memory
            await session_manager.remove_session(session_id)
            
            # Create new session with same ID (simulating restart)
            new_session_id = await session_manager.create_session(session_id)
            
            # Initialize state (should load from persistence)
            await state_manager.initialize_session_state(new_session_id, str(temp_dir))
            
            # Verify all values were restored
            for subnode_id, field_id, expected_value in field_updates:
                retrieved_value = await state_manager.get_field_value(
                    new_session_id, subnode_id, field_id
                )
                assert retrieved_value == expected_value, \
                    f"Field {subnode_id}.{field_id} should be {repr(expected_value)}, but got {repr(retrieved_value)}"
            
            # Cleanup
            await session_manager.stop()
            
        finally:
            # Clean up temp directory
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        subnode_id=subnode_ids(),
        field_id=field_ids(),
        initial_value=field_values(),
        updated_value=field_values()
    )
    async def test_field_update_persistence_roundtrip(
        self, subnode_id, field_id, initial_value, updated_value
    ):
        """
        Property: For any field that is updated multiple times, the latest 
        value persists correctly.
        
        # Feature: irisvoice-backend-integration, Property 4: Field Value Persistence Round-Trip
        """
        # Create temporary directory for persistence
        temp_dir = Path(tempfile.mkdtemp())
        
        try:
            # Create session manager and state manager
            session_manager = SessionManager()
            state_manager = StateManager(session_manager=session_manager)
            
            await session_manager.start()
            
            # Create a session
            session_id = await session_manager.create_session()
            
            # Initialize state with persistence
            await state_manager.initialize_session_state(session_id, str(temp_dir))
            
            # Set initial value
            await state_manager.update_field(
                session_id, subnode_id, field_id, initial_value
            )
            
            # Update to new value
            await state_manager.update_field(
                session_id, subnode_id, field_id, updated_value
            )
            
            # Force save to disk
            await state_manager.cleanup_session_state(session_id)
            
            # Remove session from memory
            await session_manager.remove_session(session_id)
            
            # Create new session with same ID (simulating restart)
            new_session_id = await session_manager.create_session(session_id)
            
            # Initialize state (should load from persistence)
            await state_manager.initialize_session_state(new_session_id, str(temp_dir))
            
            # Retrieve the value
            retrieved_value = await state_manager.get_field_value(
                new_session_id, subnode_id, field_id
            )
            
            # Verify the latest value was persisted (not the initial value)
            assert retrieved_value == updated_value, \
                f"Persisted value should be latest ({repr(updated_value)}), but got {repr(retrieved_value)}"
            
            # Cleanup
            await session_manager.stop()
            
        finally:
            # Clean up temp directory
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        subnode_id=subnode_ids(),
        fields=st.lists(
            st.tuples(field_ids(), field_values()),
            min_size=1,
            max_size=10
        )
    )
    async def test_subnode_fields_persistence_roundtrip(
        self, subnode_id, fields
    ):
        """
        Property: For any subnode with multiple fields, all field values 
        persist correctly together.
        
        # Feature: irisvoice-backend-integration, Property 4: Field Value Persistence Round-Trip
        """
        # Create temporary directory for persistence
        temp_dir = Path(tempfile.mkdtemp())
        
        try:
            # Create session manager and state manager
            session_manager = SessionManager()
            state_manager = StateManager(session_manager=session_manager)
            
            await session_manager.start()
            
            # Create a session
            session_id = await session_manager.create_session()
            
            # Initialize state with persistence
            await state_manager.initialize_session_state(session_id, str(temp_dir))
            
            # Update all fields in the subnode
            for field_id, value in fields:
                await state_manager.update_field(
                    session_id, subnode_id, field_id, value
                )
            
            # Force save to disk
            await state_manager.cleanup_session_state(session_id)
            
            # Remove session from memory
            await session_manager.remove_session(session_id)
            
            # Create new session with same ID (simulating restart)
            new_session_id = await session_manager.create_session(session_id)
            
            # Initialize state (should load from persistence)
            await state_manager.initialize_session_state(new_session_id, str(temp_dir))
            
            # Retrieve all subnode field values
            retrieved_fields = await state_manager.get_subnode_field_values(
                new_session_id, subnode_id
            )
            
            # Verify all fields were restored
            for field_id, expected_value in fields:
                retrieved_value = retrieved_fields.get(field_id)
                assert retrieved_value == expected_value, \
                    f"Field {field_id} should be {repr(expected_value)}, but got {repr(retrieved_value)}"
            
            # Cleanup
            await session_manager.stop()
            
        finally:
            # Clean up temp directory
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
    
    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        subnode_id=subnode_ids(),
        field_id=field_ids(),
        value=field_values()
    )
    async def test_persistence_survives_multiple_restarts(
        self, subnode_id, field_id, value
    ):
        """
        Property: For any persisted field value, it survives multiple 
        session restarts.
        
        # Feature: irisvoice-backend-integration, Property 4: Field Value Persistence Round-Trip
        """
        # Create temporary directory for persistence
        temp_dir = Path(tempfile.mkdtemp())
        
        try:
            # Create session manager and state manager
            session_manager = SessionManager()
            state_manager = StateManager(session_manager=session_manager)
            
            await session_manager.start()
            
            # Create initial session
            session_id = await session_manager.create_session()
            await state_manager.initialize_session_state(session_id, str(temp_dir))
            
            # Update field value
            await state_manager.update_field(
                session_id, subnode_id, field_id, value
            )
            
            # Perform multiple restart cycles
            for restart_num in range(3):
                # Save and cleanup
                await state_manager.cleanup_session_state(session_id)
                await session_manager.remove_session(session_id)
                
                # Restart session
                session_id = await session_manager.create_session(session_id)
                await state_manager.initialize_session_state(session_id, str(temp_dir))
                
                # Verify value persists
                retrieved_value = await state_manager.get_field_value(
                    session_id, subnode_id, field_id
                )
                assert retrieved_value == value, \
                    f"After restart {restart_num + 1}, value should be {repr(value)}, but got {repr(retrieved_value)}"
            
            # Cleanup
            await session_manager.stop()
            
        finally:
            # Clean up temp directory
            if temp_dir.exists():
                shutil.rmtree(temp_dir)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
