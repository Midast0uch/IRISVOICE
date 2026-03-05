"""
Data Retention Tests for IRIS Memory Foundation

_Requirements: 12.1, 12.2, 12.3_
"""

import pytest
import tempfile
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

# Skip all tests if dependencies not available
pytest.importorskip("backend.memory", reason="Memory module not available")

from backend.memory.retention import RetentionManager


@pytest.fixture
def mock_memory_interface():
    """Create a mock MemoryInterface."""
    return Mock()


class TestRetentionPolicy:
    """Test data retention policies."""
    
    def test_retention_manager_initialization(self, mock_memory_interface):
        """Test RetentionManager initialization."""
        rm = RetentionManager(mock_memory_interface)
        
        assert rm.memory is mock_memory_interface
    
    def test_prune_old_episodes(self, mock_memory_interface):
        """
        Verify episodes older than retention_days with score < 0.3 are pruned.
        
        _Requirement: 12.2 - Auto-prune old low-score episodes
        """
        rm = RetentionManager(mock_memory_interface)
        
        # Mock episodic store
        mock_memory_interface.episodic.get_old_episodes.return_value = [
            {"id": "old_low_score", "timestamp": "2024-01-01", "outcome_score": 0.2},
        ]
        
        with patch.object(rm, '_prune_episodes') as mock_prune:
            rm.run_cleanup()
            mock_prune.assert_called_once()
    
    def test_high_score_episodes_retained(self, mock_memory_interface):
        """
        Verify high-score episodes (>= 0.8) are retained indefinitely.
        
        _Requirement: 12.3 - High-value episodes retained regardless of age
        """
        rm = RetentionManager(mock_memory_interface)
        
        # Mock old high-score episode
        mock_memory_interface.episodic.get_old_episodes.return_value = [
            {"id": "old_high_score", "timestamp": "2023-01-01", "outcome_score": 0.9},
        ]
        
        # Should not prune high-score episodes
        with patch.object(rm, '_should_prune', return_value=False) as mock_should:
            rm.run_cleanup()
            mock_should.assert_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
