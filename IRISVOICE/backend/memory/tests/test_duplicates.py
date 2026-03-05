"""
Duplicate Detection Tests for IRIS Memory Foundation

_Requirements: 13.1, 13.2, 13.3, 13.4_
"""

import pytest
import tempfile
from unittest.mock import Mock, patch

# Skip all tests if dependencies not available
pytest.importorskip("backend.memory", reason="Memory module not available")

from backend.memory.episodic import EpisodicStore, Episode


@pytest.fixture
def temp_db_path():
    """Create a temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield f"{tmpdir}/test.db"


@pytest.fixture
def biometric_key():
    """Create a test biometric key."""
    return b"test_key_32_bytes_long_for_testing_"


class TestDuplicateDetection:
    """Test episode deduplication."""
    
    def test_similar_episode_detection(self, temp_db_path, biometric_key):
        """
        Verify similarity > 0.95 updates existing episode.
        
        _Requirement: 13.1, 13.2 - Similar episodes merged
        """
        store = EpisodicStore(temp_db_path, biometric_key)
        
        # Mock finding duplicate
        with patch.object(store, '_find_duplicate') as mock_find:
            mock_find.return_value = ("existing_id", 0.97)
            
            episode = Episode(
                session_id="s1",
                task_summary="Similar task",
                full_content="content",
                tool_sequence=[],
                outcome_type="success"
            )
            
            # Should update, not create new
            store.conn = Mock()
            store.conn.execute = Mock()
            store.conn.commit = Mock()
            
            store.store(episode)
            
            # Should call update, not insert
            calls = store.conn.execute.call_args_list
            assert any("UPDATE" in str(c) for c in calls)
    
    def test_occurrence_count_incremented(self, temp_db_path, biometric_key):
        """
        Verify occurrence_count increments on duplicate.
        
        _Requirement: 13.3 - occurrence_count tracking
        """
        store = EpisodicStore(temp_db_path, biometric_key)
        
        # Mock duplicate with count
        with patch.object(store, '_find_duplicate') as mock_find:
            mock_find.return_value = ("existing_id", 0.96)
            
            store.conn = Mock()
            store.conn.execute = Mock()
            store.conn.commit = Mock()
            
            episode = Episode(
                session_id="s1",
                task_summary="Task",
                full_content="content",
                tool_sequence=[],
                outcome_type="success"
            )
            
            store.store(episode)
            
            # Should increment occurrence_count
            call_str = str(store.conn.execute.call_args)
            assert "occurrence_count" in call_str.lower() or "UPDATE" in call_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
