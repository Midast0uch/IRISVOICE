"""
Property-based tests for field update confirmation.

Feature: irisvoice-backend-integration
Property 18: Field Update Confirmation

For any field update that passes validation, the State_Manager shall persist
the value and send a field_updated message with valid=true.

Validates: Requirements 6.3, 6.6
"""

import pytest
from hypothesis import given, strategies as st, settings
import sys
import os
import tempfile
import shutil
import asyncio
from unittest.mock import Mock, AsyncMock, patch

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.state_manager import StateManager
from backend.sessions.session_manager import SessionManager


# Test data generators
@st.composite
def valid_field_values(draw):
    """Generate valid field values."""
    return draw(st.one_of(
        st.text(min_size=0, max_size=100),
        st.integers(min_value=0, max_value=100),
        st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        st.booleans()
    ))


@st.composite
def subnode_ids(draw):
    """Generate valid subnode IDs."""
    return draw(st.sampled_from([
        "input", "output", "processing", "audio_model",
        "identity", "wake", "speech", "memory"
    ]))


@st.composite
def field_ids(draw):
    """Generate valid field IDs."""
    return draw(st.sampled_from([
        "input_device", "output_device", "sample_rate",
        "assistant_name", "personality", "wake_phrase",
        "tts_voice", "speaking_rate", "max_messages"
    ]))


@st.composite
def session_ids(draw):
    """Generate valid session IDs."""
    return draw(st.uuids()).hex


@given(
    session_id=session_ids(),
    subnode_id=subnode_ids(),
    field_id=field_ids(),
    value=valid_field_values()
)
@settings(max_examples=100, deadline=None)
@pytest.mark.asyncio
async def test_field_update_confirmation(session_id, subnode_id, field_id, value):
    """
    Property 18: Field Update Confirmation
    
    For any field update that passes validation, the State_Manager shall persist
    the value and send a field_updated message with valid=true.
    
    Validates: Requirements 6.3, 6.6
    """
    # Create temporary directory for state storage
    temp_dir = tempfile.mkdtemp()
    try:
        # Create session manager and state manager
        session_manager = SessionManager()
        state_manager = StateManager(session_manager=session_manager)
        
        # Create session with temp directory
        await session_manager.create_session(session_id, persistence_dir=temp_dir)
        
        # Update field
        success, timestamp = await state_manager.update_field(
            session_id=session_id,
            subnode_id=subnode_id,
            field_id=field_id,
            value=value
        )
        
        # Verify update succeeded
        assert success, "Field update should succeed for valid value"
        assert timestamp > 0, "Timestamp should be positive"
        
        # Verify value was persisted
        state = await state_manager.get_state(session_id)
        assert state is not None, "State should exist"
        
        # Verify value can be retrieved
        retrieved_value = await state_manager.get_field_value(
            session_id=session_id,
            subnode_id=subnode_id,
            field_id=field_id,
            default=None
        )
        
        # For numeric types, allow small floating point differences
        if isinstance(value, float) and isinstance(retrieved_value, (int, float)):
            assert abs(float(retrieved_value) - value) < 0.001, \
                f"Retrieved value {retrieved_value} should match {value}"
        else:
            assert retrieved_value == value, \
                f"Retrieved value {retrieved_value} should match {value}"
        
    finally:
        # Clean up
        shutil.rmtree(temp_dir, ignore_errors=True)


@given(
    session_id=session_ids(),
    subnode_id=subnode_ids(),
    field_id=field_ids(),
    value=valid_field_values()
)
@settings(max_examples=100, deadline=None)
@pytest.mark.asyncio
async def test_field_update_persistence_survives_reload(session_id, subnode_id, field_id, value):
    """
    Property: Field updates persist across state manager reload
    
    After updating a field and reloading the state manager, the value should
    still be retrievable.
    """
    # Create temporary directory for state storage
    temp_dir = tempfile.mkdtemp()
    try:
        # Create first state manager instance
        session_manager1 = SessionManager()
        state_manager1 = StateManager(session_manager=session_manager1)
        
        # Create session and update field
        await session_manager1.create_session(session_id, persistence_dir=temp_dir)
        success, _ = await state_manager1.update_field(
            session_id=session_id,
            subnode_id=subnode_id,
            field_id=field_id,
            value=value
        )
        assert success, "Field update should succeed"
        
        # Create second state manager instance (simulating reload)
        session_manager2 = SessionManager()
        state_manager2 = StateManager(session_manager=session_manager2)
        
        # Create session in new manager (should load persisted state)
        await session_manager2.create_session(session_id, persistence_dir=temp_dir)
        
        # Verify value persisted
        retrieved_value = await state_manager2.get_field_value(
            session_id=session_id,
            subnode_id=subnode_id,
            field_id=field_id,
            default=None
        )
        
        # For numeric types, allow small floating point differences
        if isinstance(value, float) and isinstance(retrieved_value, (int, float)):
            assert abs(float(retrieved_value) - value) < 0.001, \
                f"Retrieved value {retrieved_value} should match {value} after reload"
        else:
            assert retrieved_value == value, \
                f"Retrieved value {retrieved_value} should match {value} after reload"
        
    finally:
        # Clean up
        shutil.rmtree(temp_dir, ignore_errors=True)


@given(
    session_id=session_ids(),
    subnode_id=subnode_ids(),
    field_id=field_ids(),
    values=st.lists(valid_field_values(), min_size=2, max_size=5)
)
@settings(max_examples=100, deadline=None)
@pytest.mark.asyncio
async def test_field_update_sequence_confirmation(session_id, subnode_id, field_id, values):
    """
    Property: Multiple field updates are all confirmed
    
    For a sequence of field updates, each update should be confirmed and
    the final value should match the last update.
    """
    # Create temporary directory for state storage
    temp_dir = tempfile.mkdtemp()
    try:
        # Create session manager and state manager
        session_manager = SessionManager()
        state_manager = StateManager(session_manager=session_manager)
        
        # Create session
        await session_manager.create_session(session_id, persistence_dir=temp_dir)
        
        # Apply sequence of updates
        for value in values:
            success, _ = await state_manager.update_field(
                session_id=session_id,
                subnode_id=subnode_id,
                field_id=field_id,
                value=value
            )
            assert success, f"Field update to {value} should succeed"
        
        # Verify final value matches last update
        final_value = await state_manager.get_field_value(
            session_id=session_id,
            subnode_id=subnode_id,
            field_id=field_id,
            default=None
        )
        
        expected_value = values[-1]
        
        # For numeric types, allow small floating point differences
        if isinstance(expected_value, float) and isinstance(final_value, (int, float)):
            assert abs(float(final_value) - expected_value) < 0.001, \
                f"Final value {final_value} should match last update {expected_value}"
        else:
            assert final_value == expected_value, \
                f"Final value {final_value} should match last update {expected_value}"
        
    finally:
        # Clean up
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
