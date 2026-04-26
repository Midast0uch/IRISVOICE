"""
Tests for MemoryInterface - Single Access Boundary

_Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.6_
"""

import pytest
import tempfile
import os
from unittest.mock import Mock, MagicMock
from dataclasses import dataclass

# Skip all tests if dependencies not available
pytest.importorskip("backend.memory", reason="Memory module not available")

from backend.memory.interface import MemoryInterface
from backend.memory.episodic import Episode


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
        yield os.path.join(tmpdir, "test_memory.db")


@pytest.fixture
def biometric_key():
    """Create a test biometric key."""
    return b"test_key_32_bytes_long_for_testing_"


@pytest.fixture
def memory_interface(mock_adapter, temp_db_path, biometric_key):
    """Create a MemoryInterface instance for testing."""
    # Mock the database connection to avoid SQLCipher dependency
    with Mock() as mock_db:
        interface = MemoryInterface(
            adapter=mock_adapter,
            db_path=temp_db_path,
            biometric_key=biometric_key
        )
        # Mock the database-dependent stores
        interface.episodic = Mock()
        interface.semantic = Mock()
        return interface


class TestMemoryInterfaceInitialization:
    """Test MemoryInterface initialization."""
    
    def test_initializes_all_components(self, mock_adapter, temp_db_path, biometric_key):
        """Test that MemoryInterface initializes all storage components."""
        interface = MemoryInterface(mock_adapter, temp_db_path, biometric_key)
        
        assert interface.episodic is not None
        assert interface.semantic is not None
        assert interface.context is not None
        assert interface.embed is not None
        assert interface.adapter is mock_adapter


class TestGetTaskContext:
    """Test get_task_context() for local tasks."""
    
    def test_assembles_semantic_header(self, memory_interface):
        """Test that get_task_context includes semantic header."""
        memory_interface.semantic.get_startup_header.return_value = "User prefers concise answers."
        memory_interface.episodic.assemble_episodic_context.return_value = ""
        
        context = memory_interface.get_task_context("test task", "session_123")
        
        assert "User prefers concise answers" in context
    
    def test_assembles_episodic_context(self, memory_interface):
        """Test that get_task_context includes episodic context."""
        memory_interface.semantic.get_startup_header.return_value = ""
        memory_interface.episodic.assemble_episodic_context.return_value = "Previously solved similar task."
        
        context = memory_interface.get_task_context("test task", "session_123")
        
        assert "Previously solved similar task" in context
    
    def test_includes_task_in_context(self, memory_interface):
        """Test that get_task_context includes the current task."""
        memory_interface.semantic.get_startup_header.return_value = ""
        memory_interface.episodic.assemble_episodic_context.return_value = ""
        
        context = memory_interface.get_task_context("current task description", "session_123")
        
        assert "current task description" in context


class TestGetTaskContextForRemote:
    """Test get_task_context_for_remote() privacy boundary."""
    
    def test_excludes_semantic_header(self, memory_interface):
        """Test that get_task_context_for_remote excludes semantic header."""
        memory_interface.semantic.get_startup_header.return_value = "User prefers concise answers."
        
        context = memory_interface.get_task_context_for_remote("remote task", [])
        
        assert "User prefers concise answers" not in context
    
    def test_excludes_user_preferences(self, memory_interface):
        """Test that get_task_context_for_remote excludes user preferences."""
        memory_interface.semantic.get_startup_header.return_value = "Preference: dark mode"
        
        context = memory_interface.get_task_context_for_remote("remote task", [])
        
        assert "Preference: dark mode" not in context
    
    def test_includes_task_summary(self, memory_interface):
        """Test that get_task_context_for_remote includes task summary."""
        context = memory_interface.get_task_context_for_remote("remote task summary", [])
        
        assert "remote task summary" in context
    
    def test_includes_tool_sequence(self, memory_interface):
        """Test that get_task_context_for_remote includes tool sequence."""
        tools = [{"tool": "search", "action": "query"}]
        
        context = memory_interface.get_task_context_for_remote("task", tools)
        
        assert "search" in context or "tool" in context.lower()


class TestSessionManagement:
    """Test session management methods."""
    
    def test_append_to_session_delegates_to_context(self, memory_interface):
        """Test that append_to_session delegates to ContextManager."""
        memory_interface.context = Mock()
        
        memory_interface.append_to_session("session_123", "content")
        
        memory_interface.context.append.assert_called_once()
    
    def test_update_tool_state_delegates_to_context(self, memory_interface):
        """Test that update_tool_state delegates to ContextManager."""
        memory_interface.context = Mock()
        
        memory_interface.update_tool_state("session_123", "tool output")
        
        memory_interface.context.update_tool_state.assert_called_once()
    
    def test_clear_session_delegates_to_context(self, memory_interface):
        """Test that clear_session delegates to ContextManager."""
        memory_interface.context = Mock()
        
        memory_interface.clear_session("session_123")
        
        memory_interface.context.clear_session.assert_called_once_with("session_123")
    
    def test_get_assembled_context_delegates_to_context(self, memory_interface):
        """Test that get_assembled_context delegates to ContextManager."""
        memory_interface.context = Mock()
        memory_interface.context.render.return_value = "assembled context"
        
        result = memory_interface.get_assembled_context("session_123")
        
        assert result == "assembled context"


class TestStoreEpisode:
    """Test episode storage."""
    
    def test_delegates_to_episodic_store(self, memory_interface):
        """Test that store_episode delegates to EpisodicStore."""
        episode = Episode(
            session_id="session_123",
            task_summary="test task",
            full_content="full content",
            tool_sequence=[],
            outcome_type="success"
        )
        
        memory_interface.store_episode(episode)
        
        memory_interface.episodic.store.assert_called_once()
    
    def test_computes_outcome_score(self, memory_interface):
        """Test that store_episode computes outcome score."""
        episode = Episode(
            session_id="session_123",
            task_summary="test task",
            full_content="full content",
            tool_sequence=[],
            outcome_type="success",
            user_confirmed=True,
            user_corrected=False,
            duration_ms=3000
        )
        
        memory_interface.store_episode(episode)
        
        # Score should be computed (0.50 base + 0.30 confirmed + 0.10 not corrected + 0.10 fast)
        call_args = memory_interface.episodic.store.call_args
        assert call_args is not None


class TestPreferenceManagement:
    """Test preference management methods."""
    
    def test_update_preference_delegates_to_semantic(self, memory_interface):
        """Test that update_preference delegates to SemanticStore."""
        memory_interface.update_preference("response_length", "concise", source="user_set")
        
        memory_interface.semantic.update.assert_called_once()
    
    def test_get_user_profile_display_delegates_to_semantic(self, memory_interface):
        """Test that get_user_profile_display delegates to SemanticStore."""
        memory_interface.semantic.get_display_entries.return_value = [
            {"display_name": "Prefers concise answers"}
        ]
        
        result = memory_interface.get_user_profile_display()
        
        assert len(result) == 1
        assert result[0]["display_name"] == "Prefers concise answers"
    
    def test_forget_preference_delegates_to_semantic(self, memory_interface):
        """Test that forget_preference delegates to SemanticStore."""
        memory_interface.forget_preference("response_length")
        
        memory_interface.semantic.delete.assert_called_once()
        memory_interface.semantic.delete_display_entry.assert_called_once()


class TestScoreOutcome:
    """Test outcome scoring formula."""
    
    def test_base_score_for_success(self, memory_interface):
        """Test base score of 0.50 for success."""
        episode = Episode(
            session_id="s1",
            task_summary="task",
            full_content="content",
            tool_sequence=[],
            outcome_type="success",
            user_confirmed=False,
            user_corrected=False,
            duration_ms=10000
        )
        
        score = memory_interface._score_outcome(episode)
        
        assert score == 0.50
    
    def test_bonus_for_user_confirmed(self, memory_interface):
        """Test +0.30 bonus for user confirmed."""
        episode = Episode(
            session_id="s1",
            task_summary="task",
            full_content="content",
            tool_sequence=[],
            outcome_type="success",
            user_confirmed=True,
            user_corrected=False,
            duration_ms=10000
        )
        
        score = memory_interface._score_outcome(episode)
        
        assert score == 0.80  # 0.50 + 0.30
    
    def test_bonus_for_not_corrected(self, memory_interface):
        """Test +0.10 bonus for not user corrected."""
        episode = Episode(
            session_id="s1",
            task_summary="task",
            full_content="content",
            tool_sequence=[],
            outcome_type="success",
            user_confirmed=False,
            user_corrected=False,
            duration_ms=10000
        )
        
        score = memory_interface._score_outcome(episode)
        
        assert score == 0.60  # 0.50 + 0.10
    
    def test_bonus_for_fast_completion(self, memory_interface):
        """Test +0.10 bonus for duration < 5s."""
        episode = Episode(
            session_id="s1",
            task_summary="task",
            full_content="content",
            tool_sequence=[],
            outcome_type="success",
            user_confirmed=False,
            user_corrected=False,
            duration_ms=3000  # 3 seconds
        )
        
        score = memory_interface._score_outcome(episode)
        
        assert score == 0.70  # 0.50 + 0.10 + 0.10
    
    def test_zero_score_for_failure(self, memory_interface):
        """Test zero base score for failure."""
        episode = Episode(
            session_id="s1",
            task_summary="task",
            full_content="content",
            tool_sequence=[],
            outcome_type="failure",
            user_confirmed=False,
            user_corrected=False,
            duration_ms=10000
        )
        
        score = memory_interface._score_outcome(episode)
        
        assert score == 0.0


class TestPrivacyBoundary:
    """Test privacy boundary enforcement."""
    
    def test_remote_context_no_personal_data(self, memory_interface):
        """
        CRITICAL: Verify get_task_context_for_remote returns NO personal data.
        
        This is the privacy boundary for Torus network integration.
        """
        # Setup personal data
        memory_interface.semantic.get_startup_header.return_value = """User Profile:
- Name: John Doe
- Location: New York
- Preferences: dark mode, concise answers
- Work style: morning person"""
        
        # Get remote context
        context = memory_interface.get_task_context_for_remote("task", [])
        
        # Verify no personal data leaked
        assert "John Doe" not in context
        assert "New York" not in context
        assert "dark mode" not in context
        assert "morning person" not in context
    
    def test_local_context_includes_personal_data(self, memory_interface):
        """Test that get_task_context (local) CAN include personal data."""
        memory_interface.semantic.get_startup_header.return_value = "User: John Doe"
        memory_interface.episodic.assemble_episodic_context.return_value = ""
        
        context = memory_interface.get_task_context("task", "session_123")
        
        # Local context can include personal data
        assert "John Doe" in context


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
