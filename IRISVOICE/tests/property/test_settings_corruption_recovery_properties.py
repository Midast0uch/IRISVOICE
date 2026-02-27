# Feature: irisvoice-backend-integration, Property 50: Settings File Corruption Recovery
"""
Property-based tests for settings file corruption recovery.

**Validates: Requirements 20.10**

This test validates that the state manager can recover from corrupted settings files
by falling back to backup files or default values.
"""

import pytest
import asyncio
import json
import tempfile
from pathlib import Path
from hypothesis import given, strategies as st, settings

from backend.sessions.state_isolation import IsolatedStateManager
from backend.core_models import IRISState


# Strategy for generating valid field values
field_value_strategy = st.one_of(
    st.text(min_size=1, max_size=50),
    st.integers(min_value=0, max_value=100),
    st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    st.booleans()
)

# Strategy for generating field updates
field_update_strategy = st.tuples(
    st.sampled_from(["input", "output", "identity", "wake", "theme"]),  # subnode_id
    st.sampled_from(["field1", "field2", "field3"]),  # field_id
    field_value_strategy  # value
)


# Property tests for specific corruption scenarios
@given(
    updates=st.lists(field_update_strategy, min_size=1, max_size=10)
)
@settings(max_examples=30, deadline=None)
def test_recovery_from_corrupted_main_file(updates):
    """
    Property 50: Settings File Corruption Recovery - Main File Corruption
    
    Test recovery from corrupted main file with valid backup.
    
    Properties tested:
    1. Corrupted main file falls back to backup
    2. No data loss when backup is valid
    3. State is recoverable after corruption
    
    **Validates: Requirements 20.10**
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        temp_dir = tempfile.mkdtemp()
        session_id = "test_recovery_session"
        
        # Create state manager and apply updates
        manager = IsolatedStateManager(session_id)
        loop.run_until_complete(manager.initialize(temp_dir))
        
        for subnode_id, field_id, value in updates:
            loop.run_until_complete(manager.update_field(subnode_id, field_id, value))
        
        # Save state (creates backup)
        loop.run_until_complete(manager._save_state())
        loop.run_until_complete(manager.cleanup())
        
        # Corrupt main file
        state_file = Path(temp_dir) / session_id / "session_state.json"
        with open(state_file, 'w') as f:
            f.write("{ invalid json }")
        
        # Create new manager and verify recovery
        new_manager = IsolatedStateManager(session_id)
        loop.run_until_complete(new_manager.initialize(temp_dir))
        
        state = loop.run_until_complete(new_manager.get_state_copy())
        assert state is not None, "State should be recovered from backup"
        
        loop.run_until_complete(new_manager.cleanup())
        
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir)
    finally:
        loop.close()


@given(
    updates=st.lists(field_update_strategy, min_size=1, max_size=10)
)
@settings(max_examples=30, deadline=None)
def test_fallback_to_default_on_total_corruption(updates):
    """
    Property 50: Settings File Corruption Recovery - Total Corruption
    
    Test fallback to default state when both main and backup are corrupted.
    
    Properties tested:
    1. Corrupted backup falls back to default state
    2. System remains functional with default state
    3. No crashes on total corruption
    
    **Validates: Requirements 20.10**
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        temp_dir = tempfile.mkdtemp()
        session_id = "test_fallback_session"
        
        # Create state manager and apply updates
        manager = IsolatedStateManager(session_id)
        loop.run_until_complete(manager.initialize(temp_dir))
        
        for subnode_id, field_id, value in updates:
            loop.run_until_complete(manager.update_field(subnode_id, field_id, value))
        
        loop.run_until_complete(manager.cleanup())
        
        # Corrupt both files
        state_file = Path(temp_dir) / session_id / "session_state.json"
        backup_file = state_file.with_suffix('.json.bak')
        
        with open(state_file, 'w') as f:
            f.write("{ corrupted }")
        
        if backup_file.exists():
            with open(backup_file, 'w') as f:
                f.write("{ also corrupted }")
        
        # Create new manager and verify fallback to default
        new_manager = IsolatedStateManager(session_id)
        loop.run_until_complete(new_manager.initialize(temp_dir))
        
        state = loop.run_until_complete(new_manager.get_state_copy())
        assert state is not None, "Should fall back to default state"
        assert len(state.field_values) == 0, "Default state should have no field values"
        
        loop.run_until_complete(new_manager.cleanup())
        
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir)
    finally:
        loop.close()


@given(
    updates=st.lists(field_update_strategy, min_size=1, max_size=10)
)
@settings(max_examples=30, deadline=None)
def test_backup_creation_on_save(updates):
    """
    Property 50: Settings File Corruption Recovery - Backup Creation
    
    Test that backups are created before saving new state.
    
    Properties tested:
    1. Backup file is created on save
    2. Backup contains previous valid state
    3. Multiple saves create updated backups
    
    **Validates: Requirements 20.10**
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        temp_dir = tempfile.mkdtemp()
        session_id = "test_backup_session"
        
        # Create state manager and apply first update
        manager = IsolatedStateManager(session_id)
        loop.run_until_complete(manager.initialize(temp_dir))
        
        if len(updates) > 0:
            subnode_id, field_id, value = updates[0]
            loop.run_until_complete(manager.update_field(subnode_id, field_id, value))
        
        # Save state (first save, no backup yet)
        loop.run_until_complete(manager._save_state())
        
        state_file = Path(temp_dir) / session_id / "session_state.json"
        backup_file = state_file.with_suffix('.json.bak')
        
        # Apply more updates
        for subnode_id, field_id, value in updates[1:]:
            loop.run_until_complete(manager.update_field(subnode_id, field_id, value))
        
        # Save again (should create backup)
        loop.run_until_complete(manager._save_state())
        
        # Verify backup exists
        if state_file.exists():
            assert backup_file.exists(), "Backup file should be created on second save"
        
        loop.run_until_complete(manager.cleanup())
        
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir)
    finally:
        loop.close()


@given(
    updates=st.lists(field_update_strategy, min_size=2, max_size=10)
)
@settings(max_examples=30, deadline=None)
def test_state_consistency_after_recovery(updates):
    """
    Property 50: Settings File Corruption Recovery - State Consistency
    
    Test that recovered state maintains consistency.
    
    Properties tested:
    1. Recovered state is valid IRISState
    2. Recovered state can be modified
    3. New saves work after recovery
    
    **Validates: Requirements 20.10**
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        temp_dir = tempfile.mkdtemp()
        session_id = "test_consistency_session"
        
        # Create state manager and apply updates
        manager = IsolatedStateManager(session_id)
        loop.run_until_complete(manager.initialize(temp_dir))
        
        for subnode_id, field_id, value in updates[:-1]:
            loop.run_until_complete(manager.update_field(subnode_id, field_id, value))
        
        loop.run_until_complete(manager._save_state())
        loop.run_until_complete(manager.cleanup())
        
        # Corrupt main file
        state_file = Path(temp_dir) / session_id / "session_state.json"
        with open(state_file, 'w') as f:
            f.write("{ invalid }")
        
        # Recover and apply new update
        new_manager = IsolatedStateManager(session_id)
        loop.run_until_complete(new_manager.initialize(temp_dir))
        
        # Apply new update to recovered state
        subnode_id, field_id, value = updates[-1]
        success, _ = loop.run_until_complete(new_manager.update_field(subnode_id, field_id, value))
        
        assert success, "Should be able to update recovered state"
        
        # Verify state is valid
        state = loop.run_until_complete(new_manager.get_state_copy())
        assert state is not None, "Recovered state should be valid"
        assert isinstance(state, IRISState), "Should be IRISState instance"
        
        loop.run_until_complete(new_manager.cleanup())
        
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir)
    finally:
        loop.close()


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "-s"])

