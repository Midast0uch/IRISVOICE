"""
Privacy Boundary Tests for IRIS Memory Foundation

_Requirements: 4.6, 10.5, 10.6_
"""

import pytest
import tempfile
import os
from unittest.mock import Mock

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
        yield os.path.join(tmpdir, "privacy_test.db")


@pytest.fixture
def biometric_key():
    """Create a test biometric key."""
    return b"test_key_32_bytes_long_for_testing_"


class TestPrivacyBoundary:
    """Test privacy boundary enforcement."""
    
    def test_remote_context_no_semantic_header(self, mock_adapter, temp_db_path, biometric_key):
        """
        CRITICAL: Verify get_task_context_for_remote returns no semantic_header.
        
        _Requirement: 4.6, 10.5 - Remote context must exclude personal data
        """
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        # Setup personal data
        memory.semantic.get_startup_header.return_value = """User Profile:
- Name: John Doe
- Email: john@example.com"""
        
        context = memory.get_task_context_for_remote("task", [])
        
        assert "John Doe" not in context
        assert "john@example.com" not in context
    
    def test_remote_context_no_preferences(self, mock_adapter, temp_db_path, biometric_key):
        """Verify get_task_context_for_remote returns no user preferences."""
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        memory.semantic.get_startup_header.return_value = """Preferences:
- Dark mode enabled
- Location: New York
- Work hours: 9-5"""
        
        context = memory.get_task_context_for_remote("task", [])
        
        assert "dark mode" not in context.lower()
        assert "New York" not in context
        assert "work hours" not in context.lower()
    
    def test_remote_context_no_cognitive_model(self, mock_adapter, temp_db_path, biometric_key):
        """Verify remote context excludes cognitive model."""
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        memory.semantic.get_startup_header.return_value = """Cognitive Model:
- Analytical thinking style
- Prefers detailed explanations"""
        
        context = memory.get_task_context_for_remote("task", [])
        
        assert "analytical" not in context.lower()
        assert "thinking style" not in context.lower()
    
    def test_remote_context_no_domain_knowledge(self, mock_adapter, temp_db_path, biometric_key):
        """Verify remote context excludes domain knowledge."""
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        memory.semantic.get_startup_header.return_value = """Domain Knowledge:
- Expert in Python
- Works at TechCorp"""
        
        context = memory.get_task_context_for_remote("task", [])
        
        assert "expert" not in context.lower()
        assert "TechCorp" not in context
    
    def test_remote_context_includes_task_only(self, mock_adapter, temp_db_path, biometric_key):
        """Verify remote context includes only task-relevant info."""
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        context = memory.get_task_context_for_remote(
            task_summary="Search for Python documentation",
            tool_sequence=[{"tool": "search", "action": "query"}]
        )
        
        # Should include task info
        assert "Python" in context or "search" in context.lower()


class TestLocalContext:
    """Test that local context CAN include personal data."""
    
    def test_local_context_includes_semantic_header(self, mock_adapter, temp_db_path, biometric_key):
        """Verify get_task_context (local) includes semantic header."""
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        memory.semantic.get_startup_header.return_value = "User: John Doe"
        memory.episodic.assemble_episodic_context.return_value = ""
        
        context = memory.get_task_context("task", "session_123")
        
        assert "John Doe" in context


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
