"""
User Display Tests for IRIS Memory Foundation

_Requirements: 3.5, 3.6, 11.7, 11.8_
"""

import pytest
import tempfile
from unittest.mock import Mock, patch

# Skip all tests if dependencies not available
pytest.importorskip("backend.memory", reason="Memory module not available")

from backend.memory.interface import MemoryInterface


@pytest.fixture
def mock_adapter():
    """Create a mock model adapter."""
    adapter = Mock()
    adapter.get_context_size.return_value = 8192
    adapter.count_tokens.return_value = 100
    return adapter


@pytest.fixture
def temp_db_path():
    """Create a temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield f"{tmpdir}/test.db"


@pytest.fixture
def biometric_key():
    """Create a test biometric key."""
    return b"test_key_32_bytes_long_for_testing_"


class TestUserProfileDisplay:
    """Test user-facing preference display."""
    
    def test_get_user_profile_display_returns_entries(self, mock_adapter, temp_db_path, biometric_key):
        """
        Verify get_user_profile_display returns entries after interactions.
        
        _Requirement: 3.5 - User-facing display of learned preferences
        """
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        # Mock display entries
        memory.semantic.get_display_entries.return_value = [
            {"display_name": "Prefers concise answers", "confidence": 1.0},
            {"display_name": "Dark mode enabled", "confidence": 0.9}
        ]
        
        entries = memory.get_user_profile_display()
        
        assert len(entries) == 2
        assert entries[0]["display_name"] == "Prefers concise answers"
    
    def test_forget_removes_from_display(self, mock_adapter, temp_db_path, biometric_key):
        """
        Verify forget removes preference from display and header.
        
        _Requirement: 3.6 - Forget removes from both tables
        """
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        with patch.object(memory.semantic, 'delete') as mock_delete:
            with patch.object(memory.semantic, 'delete_display_entry') as mock_display_delete:
                memory.forget_preference("response_length")
                
                # Should delete from both tables
                mock_delete.assert_called_once()
                mock_display_delete.assert_called_once()
    
    def test_display_entries_editable(self, mock_adapter, temp_db_path, biometric_key):
        """Verify display entries have editable flag."""
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        memory.semantic.get_display_entries.return_value = [
            {"display_name": "Test", "editable": 1},
            {"display_name": "Auto-learned", "editable": 0}
        ]
        
        entries = memory.get_user_profile_display()
        
        # Check editable flags
        assert entries[0]["editable"] == 1
        assert entries[1]["editable"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
