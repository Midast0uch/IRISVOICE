"""
Property-based tests for state update ordering.
Tests that state updates with timestamps are handled correctly even when out-of-order.
"""
import pytest
import asyncio
from datetime import datetime, timedelta
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


@st.composite
def timestamped_updates(draw):
    """Generate a list of timestamped field updates with potential out-of-order timestamps."""
    num_updates = draw(st.integers(min_value=2, max_value=10))
    
    # Generate base timestamp
    base_time = datetime.now()
    
    # Generate updates with sequential timestamps
    updates = []
    for i in range(num_updates):
        subnode_id = draw(subnode_ids())
        field_id = draw(field_ids())
        value = draw(field_values())
        timestamp = base_time + timedelta(seconds=i)
        updates.append((subnode_id, field_id, value, timestamp))
    
    # Shuffle to create out-of-order delivery
    shuffled_updates = draw(st.permutations(updates))
    
    return list(shuffled_updates)


# ============================================================================
# Property 51: State Update Ordering
# Feature: irisvoice-backend-integration, Property 51: State Update Ordering
# Validates: Requirements 21.6, 21.7
# ============================================================================

class TestStateUpdateOrdering:
    """
    Property 51: State Update Ordering
    
    For any sequence of state updates with timestamps, the State_Manager 
    shall handle out-of-order updates gracefully using the timestamp to 
    determine the latest value.
    """
    
    @pytest.mark.asyncio
    @settings(max_examples=20, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(updates=timestamped_updates())
    async def test_out_of_order_updates_use_latest_timestamp(self, updates):
        """
        Property: For any sequence of out-of-order updates, the state manager 
        uses timestamps to determine the latest value.
        
        # Feature: irisvoice-backend-integration, Property 51: State Update Ordering
        """
        # Create session manager and state manager
        session_manager = SessionManager()
        state_manager = StateManager(session_manager=session_manager)
        
        await session_manager.start()
        
        try:
            # Create a session
            session_id = await session_manager.create_session()
            
            # Apply updates in the shuffled (out-of-order) sequence
            for subnode_id, field_id, value, timestamp in updates:
                # Update field with timestamp (convert datetime to float timestamp)
                success, _ = await state_manager.update_field(
                    session_id, subnode_id, field_id, value, timestamp.timestamp()
                )
                # Note: success may be False for out-of-order updates (older timestamps)
            
            # Determine the expected final values (latest timestamp for each field)
            expected_values = {}
            for subnode_id, field_id, value, timestamp in updates:
                key = (subnode_id, field_id)
                if key not in expected_values or timestamp > expected_values[key][1]:
                    expected_values[key] = (value, timestamp)
            
            # Verify that the final state contains the values with the latest timestamps
            for (subnode_id, field_id), (expected_value, _) in expected_values.items():
                retrieved_value = await state_manager.get_field_value(
                    session_id, subnode_id, field_id
                )
                assert retrieved_value == expected_value, \
                    f"Field {subnode_id}.{field_id} should have latest value {repr(expected_value)}, but got {repr(retrieved_value)}"
            
            # Cleanup
            await session_manager.stop()
            
        except Exception as e:
            await session_manager.stop()
            raise
    
    @pytest.mark.asyncio
    @settings(max_examples=20, deadline=None)
    @seed(42)
    @given(
        subnode_id=subnode_ids(),
        field_id=field_ids(),
        old_value=field_values(),
        new_value=field_values()
    )
    async def test_older_update_does_not_overwrite_newer(
        self, subnode_id, field_id, old_value, new_value
    ):
        """
        Property: For any field, an update with an older timestamp does not 
        overwrite a value with a newer timestamp.
        
        # Feature: irisvoice-backend-integration, Property 51: State Update Ordering
        """
        # Create session manager and state manager
        session_manager = SessionManager()
        state_manager = StateManager(session_manager=session_manager)
        
        await session_manager.start()
        
        try:
            # Create a session
            session_id = await session_manager.create_session()
            
            # Create timestamps
            newer_timestamp = datetime.now()
            older_timestamp = newer_timestamp - timedelta(seconds=10)
            
            # Apply newer update first
            success, _ = await state_manager.update_field(
                session_id, subnode_id, field_id, new_value, newer_timestamp.timestamp()
            )
            assert success
            
            # Apply older update (should be ignored)
            success, _ = await state_manager.update_field(
                session_id, subnode_id, field_id, old_value, older_timestamp.timestamp()
            )
            # Update should return False because timestamp is older
            assert not success, "Older update should be rejected"
            
            # Verify the newer value is retained
            retrieved_value = await state_manager.get_field_value(
                session_id, subnode_id, field_id
            )
            assert retrieved_value == new_value, \
                f"Field should retain newer value {repr(new_value)}, but got {repr(retrieved_value)}"
            
            # Cleanup
            await session_manager.stop()
            
        except Exception as e:
            await session_manager.stop()
            raise
    
    @pytest.mark.asyncio
    @settings(max_examples=20, deadline=None)
    @seed(42)
    @given(
        subnode_id=subnode_ids(),
        field_id=field_ids(),
        values=st.lists(field_values(), min_size=3, max_size=10)
    )
    async def test_multiple_updates_same_field_uses_latest(
        self, subnode_id, field_id, values
    ):
        """
        Property: For any field with multiple updates, the value with the 
        latest timestamp is retained.
        
        # Feature: irisvoice-backend-integration, Property 51: State Update Ordering
        """
        # Create session manager and state manager
        session_manager = SessionManager()
        state_manager = StateManager(session_manager=session_manager)
        
        await session_manager.start()
        
        try:
            # Create a session
            session_id = await session_manager.create_session()
            
            # Create timestamped updates
            base_time = datetime.now()
            timestamped_values = [
                (value, base_time + timedelta(seconds=i))
                for i, value in enumerate(values)
            ]
            
            # Shuffle the updates to simulate out-of-order delivery
            import random
            shuffled = timestamped_values.copy()
            random.shuffle(shuffled)
            
            # Apply all updates
            for value, timestamp in shuffled:
                await state_manager.update_field(
                    session_id, subnode_id, field_id, value, timestamp.timestamp()
                )
            
            # The latest value should be the one with the highest timestamp
            expected_value = timestamped_values[-1][0]  # Last in original sequence
            
            # Verify the latest value is retained
            retrieved_value = await state_manager.get_field_value(
                session_id, subnode_id, field_id
            )
            assert retrieved_value == expected_value, \
                f"Field should have latest value {repr(expected_value)}, but got {repr(retrieved_value)}"
            
            # Cleanup
            await session_manager.stop()
            
        except Exception as e:
            await session_manager.stop()
            raise
    
    @pytest.mark.asyncio
    @settings(max_examples=20, deadline=None)
    @seed(42)
    @given(
        updates=st.lists(
            st.tuples(subnode_ids(), field_ids(), field_values()),
            min_size=2,
            max_size=10
        )
    )
    async def test_concurrent_updates_different_fields_all_applied(self, updates):
        """
        Property: For any set of concurrent updates to different fields, 
        all updates are applied correctly regardless of order.
        
        # Feature: irisvoice-backend-integration, Property 51: State Update Ordering
        """
        # Create session manager and state manager
        session_manager = SessionManager()
        state_manager = StateManager(session_manager=session_manager)
        
        await session_manager.start()
        
        try:
            # Create a session
            session_id = await session_manager.create_session()
            
            # Create timestamped updates (all with same timestamp to simulate concurrency)
            timestamp = datetime.now()
            
            # Apply all updates
            for subnode_id, field_id, value in updates:
                await state_manager.update_field(
                    session_id, subnode_id, field_id, value, timestamp.timestamp()
                )
            
            # Verify all updates were applied
            for subnode_id, field_id, expected_value in updates:
                retrieved_value = await state_manager.get_field_value(
                    session_id, subnode_id, field_id
                )
                assert retrieved_value == expected_value, \
                    f"Field {subnode_id}.{field_id} should be {repr(expected_value)}, but got {repr(retrieved_value)}"
            
            # Cleanup
            await session_manager.stop()
            
        except Exception as e:
            await session_manager.stop()
            raise
    
    @pytest.mark.asyncio
    @settings(max_examples=20, deadline=None)
    @seed(42)
    @given(
        subnode_id=subnode_ids(),
        field_id=field_ids(),
        value1=field_values(),
        value2=field_values(),
        value3=field_values()
    )
    async def test_timestamp_comparison_handles_microseconds(
        self, subnode_id, field_id, value1, value2, value3
    ):
        """
        Property: For any updates with timestamps differing by microseconds, 
        the state manager correctly identifies the latest.
        
        # Feature: irisvoice-backend-integration, Property 51: State Update Ordering
        """
        # Create session manager and state manager
        session_manager = SessionManager()
        state_manager = StateManager(session_manager=session_manager)
        
        await session_manager.start()
        
        try:
            # Create a session
            session_id = await session_manager.create_session()
            
            # Create timestamps with microsecond differences
            base_time = datetime.now()
            timestamp1 = base_time
            timestamp2 = base_time + timedelta(microseconds=100)
            timestamp3 = base_time + timedelta(microseconds=200)
            
            # Apply updates in reverse order
            await state_manager.update_field(
                session_id, subnode_id, field_id, value3, timestamp3.timestamp()
            )
            await state_manager.update_field(
                session_id, subnode_id, field_id, value1, timestamp1.timestamp()
            )
            await state_manager.update_field(
                session_id, subnode_id, field_id, value2, timestamp2.timestamp()
            )
            
            # The latest value (value3 with timestamp3) should be retained
            retrieved_value = await state_manager.get_field_value(
                session_id, subnode_id, field_id
            )
            assert retrieved_value == value3, \
                f"Field should have latest value {repr(value3)}, but got {repr(retrieved_value)}"
            
            # Cleanup
            await session_manager.stop()
            
        except Exception as e:
            await session_manager.stop()
            raise


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
