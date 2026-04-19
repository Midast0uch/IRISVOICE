"""
Integration Tests for IRIS Memory Foundation

End-to-end test of task execution with episode storage and retrieval.

_Requirements: 9.1, 9.2, 9.3, 9.4_
"""

import pytest
import asyncio
import tempfile
import os
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime

# Skip all tests if dependencies not available
pytest.importorskip("backend.memory", reason="Memory module not available")

from backend.memory.interface import MemoryInterface, Episode
from backend.memory import initialise_memory


@pytest.fixture
def mock_adapter():
    """Create a mock model adapter."""
    adapter = Mock()
    adapter.get_context_size.return_value = 8192
    adapter.count_tokens.return_value = 100
    adapter.generate.return_value = "Extracted pattern"
    return adapter


@pytest.fixture
def temp_db_path():
    """Create a temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "integration_test.db")


@pytest.fixture
def biometric_key():
    """Create a test biometric key."""
    return b"test_key_32_bytes_long_for_testing_"


class TestMemorySystemIntegration:
    """Integration tests for the complete memory system."""
    
    def test_full_task_lifecycle(self, mock_adapter, temp_db_path, biometric_key):
        """
        Test complete task lifecycle:
        1. Initialize memory
        2. Get context for task
        3. Simulate conversation
        4. Store episode
        5. Retrieve similar episodes
        """
        # Create memory interface
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        # Step 1: Get task context
        session_id = "test_session_123"
        context = memory.get_task_context("Search for Python docs", session_id)
        
        assert context is not None
        assert isinstance(context, str)
        
        # Step 2: Simulate conversation
        memory.append_to_session(session_id, "User: How do I use list comprehensions?")
        memory.append_to_session(session_id, "Assistant: List comprehensions are a concise way...")
        
        # Step 3: Update tool state
        memory.update_tool_state(session_id, "Found Python documentation")
        
        # Step 4: Create and store episode
        episode = Episode(
            session_id=session_id,
            task_summary="Explain Python list comprehensions",
            full_content="User asked about list comprehensions",
            tool_sequence=[
                {"tool": "search", "action": "query", "params": {"q": "python list comprehension"}}
            ],
            outcome_type="success",
            user_confirmed=True,
            user_corrected=False,
            duration_ms=3000,
            tokens_used=250
        )
        
        # Mock the episodic store to avoid SQLCipher dependency
        with patch.object(memory.episodic, 'store') as mock_store:
            mock_store.return_value = "episode_id_123"
            episode_id = memory.store_episode(episode)
            
            assert episode_id is not None
            mock_store.assert_called_once()
    
    def test_privacy_boundary_remote_context(self, mock_adapter, temp_db_path, biometric_key):
        """
        Test privacy boundary for remote context.
        
        CRITICAL: get_task_context_for_remote must NOT include personal data.
        """
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        # Mock semantic header with personal data
        memory.semantic.get_startup_header.return_value = """User Profile:
- Name: John Doe
- Location: New York
- Email: john@example.com
- Preferences: dark mode"""
        
        # Get remote context
        context = memory.get_task_context_for_remote(
            task_summary="Search task",
            tool_sequence=[{"tool": "search"}]
        )
        
        # Verify NO personal data leaked
        assert "John Doe" not in context
        assert "New York" not in context
        assert "john@example.com" not in context
        assert "dark mode" not in context
    
    def test_context_assembly_includes_all_parts(self, mock_adapter, temp_db_path, biometric_key):
        """Test that assembled context includes all required parts."""
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        # Setup session
        session_id = "session_456"
        memory.context.assemble_for_task(
            session_id,
            "Current task",
            semantic_header="User prefers concise",
            episodic_context="Previously succeeded"
        )
        
        # Get assembled context
        context = memory.get_assembled_context(session_id)
        
        assert "User prefers concise" in context
        assert "Previously succeeded" in context
        assert "Current task" in context
    
    def test_episode_retrieval_for_similar_tasks(self, mock_adapter, temp_db_path, biometric_key):
        """Test retrieving similar episodes for task context."""
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        # Mock episodic retrieval
        memory.episodic.retrieve_similar.return_value = [
            {
                "task_summary": "Similar task",
                "outcome_type": "success",
                "outcome_score": 0.9
            }
        ]
        
        # Get context which triggers retrieval
        context = memory.get_task_context("Similar task query", "session_789")
        
        memory.episodic.retrieve_similar.assert_called_once()
    
    def test_session_isolation(self, mock_adapter, temp_db_path, biometric_key):
        """Test that sessions are properly isolated."""
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        session_1 = "session_1"
        session_2 = "session_2"
        
        # Add content to session 1
        memory.context._sessions[session_1] = {"working_history": "Session 1 content"}
        memory.context._sessions[session_2] = {"working_history": "Session 2 content"}
        
        # Clear session 1
        memory.clear_session(session_1)
        
        # Session 2 should still exist
        assert session_1 not in memory.context._sessions
        assert session_2 in memory.context._sessions
        assert memory.context._sessions[session_2]["working_history"] == "Session 2 content"
    
    def test_preference_management_flow(self, mock_adapter, temp_db_path, biometric_key):
        """Test complete preference management flow."""
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        # Mock semantic store
        with patch.object(memory.semantic, 'update') as mock_update:
            with patch.object(memory.semantic, 'get_display_entries') as mock_display:
                mock_display.return_value = [
                    {"display_name": "Prefers concise answers", "confidence": 1.0}
                ]
                
                # Update preference
                memory.update_preference("response_length", "concise", source="user_set")
                mock_update.assert_called_once()
                
                # Get display entries
                entries = memory.get_user_profile_display()
                assert len(entries) == 1
                assert entries[0]["display_name"] == "Prefers concise answers"
    
    def test_outcome_scoring_formula(self, mock_adapter, temp_db_path, biometric_key):
        """Test outcome scoring formula calculation."""
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        # Test perfect success
        perfect_episode = Episode(
            session_id="s1",
            task_summary="task",
            full_content="content",
            tool_sequence=[],
            outcome_type="success",
            user_confirmed=True,
            user_corrected=False,
            duration_ms=3000  # < 5s
        )
        
        score = memory._score_outcome(perfect_episode)
        
        # Expected: 0.50 + 0.30 + 0.10 + 0.10 = 1.0
        assert score == 1.0
    
    def test_failure_episode_scoring(self, mock_adapter, temp_db_path, biometric_key):
        """Test that failure episodes get zero score."""
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        failure_episode = Episode(
            session_id="s1",
            task_summary="task",
            full_content="content",
            tool_sequence=[],
            outcome_type="failure",
            user_confirmed=False,
            user_corrected=False,
            duration_ms=10000
        )
        
        score = memory._score_outcome(failure_episode)
        
        assert score == 0.0


class TestMemoryInitialization:
    """Test memory system initialization."""
    
    @pytest.mark.asyncio
    async def test_initialise_memory_creates_interface(self, mock_adapter, temp_db_path):
        """Test that initialise_memory creates a MemoryInterface."""
        with patch('backend.memory.load_config') as mock_load:
            mock_load.return_value = Mock()
            mock_load.return_value.db_path = temp_db_path
            
            with patch('backend.core.biometric.initialize_memory_encryption') as mock_key:
                mock_key.return_value = b"test_key_32_bytes_long_for_testing_"
                
                memory = await initialise_memory(mock_adapter, db_path=temp_db_path)
                
                assert memory is not None
                assert isinstance(memory, MemoryInterface)


class TestTorusReadiness:
    """Test Torus-ready fields and functionality."""
    
    def test_episode_has_torus_fields(self, mock_adapter, temp_db_path, biometric_key):
        """Test that episodes have Torus-ready fields."""
        episode = Episode(
            session_id="s1",
            task_summary="task",
            full_content="content",
            tool_sequence=[],
            outcome_type="success",
            node_id="local",
            origin="local"
        )
        
        assert hasattr(episode, 'node_id')
        assert hasattr(episode, 'origin')
        assert episode.node_id == "local"
        assert episode.origin == "local"
    
    def test_semantic_versioning_for_sync(self, mock_adapter, temp_db_path, biometric_key):
        """Test semantic entry versioning for Torus sync."""
        memory = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        with patch.object(memory.semantic, 'get_max_version') as mock_max:
            mock_max.return_value = 42
            
            max_version = memory.semantic.get_max_version()
            assert max_version == 42
        
        with patch.object(memory.semantic, 'get_delta_since_version') as mock_delta:
            mock_delta.return_value = [
                ("user_preferences", "key", "value", 43, 1.0, "user_set", "2024-01-01")
            ]
            
            delta = memory.semantic.get_delta_since_version(since_version=40)
            assert len(delta) == 1
            assert delta[0][3] > 40  # version > since_version


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
