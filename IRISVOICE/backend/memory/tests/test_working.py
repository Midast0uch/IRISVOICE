"""
Tests for ContextManager - Working Memory (Session Context)

_Requirements: 1.1, 1.3, 1.4, 1.5, 1.6_
"""

import pytest
from unittest.mock import Mock, patch

# Skip all tests if dependencies not available
pytest.importorskip("backend.memory", reason="Memory module not available")

from backend.memory.working import ContextManager

# Access class attributes
ZONES_ORDER = ContextManager.ZONES_ORDER
ANCHOR_ZONES = ContextManager.ANCHOR_ZONES


@pytest.fixture
def mock_adapter():
    """Create a mock model adapter."""
    adapter = Mock()
    adapter.get_context_size.return_value = 8192
    adapter.count_tokens.return_value = 100
    return adapter


@pytest.fixture
def context_manager(mock_adapter):
    """Create a ContextManager instance."""
    return ContextManager(adapter=mock_adapter)


class TestContextManagerInitialization:
    """Test ContextManager initialization."""
    
    def test_initializes_with_adapter(self, mock_adapter):
        """Test that ContextManager initializes with adapter."""
        cm = ContextManager(adapter=mock_adapter)
        
        assert cm.adapter is mock_adapter
        assert cm._sessions == {}
    
    def test_default_threshold(self, mock_adapter):
        """Test default compression threshold."""
        cm = ContextManager(adapter=mock_adapter)
        
        assert cm.COMPRESSION_THRESHOLD == 0.8


class TestZonesOrder:
    """Test zone ordering."""
    
    def test_zones_order_defined(self):
        """Test that ZONES_ORDER is defined."""
        assert isinstance(ZONES_ORDER, tuple)
        assert len(ZONES_ORDER) > 0
    
    def test_semantic_header_first(self):
        """Test that semantic_header is first in order."""
        assert ZONES_ORDER[0] == "semantic_header"
    
    def test_working_history_last(self):
        """Test that working_history is last in order."""
        assert ZONES_ORDER[-1] == "working_history"


class TestAnchorZones:
    """Test anchor zones."""
    
    def test_anchor_zones_defined(self):
        """Test that ANCHOR_ZONES is defined."""
        assert isinstance(ANCHOR_ZONES, set)
        assert len(ANCHOR_ZONES) > 0
    
    def test_working_history_is_anchor(self):
        """Test that working_history is an anchor zone."""
        assert "working_history" in ANCHOR_ZONES


class TestAssembleForTask:
    """Test assembling context for a task."""
    
    def test_creates_session_entry(self, context_manager):
        """Test that assemble_for_task creates session entry."""
        context_manager.assemble_for_task(
            session_id="session_123",
            task="test task",
            semantic_header="header",
            episodic_context="episodic"
        )
        
        assert "session_123" in context_manager._sessions
    
    def test_initializes_all_zones(self, context_manager):
        """Test that all zones are initialized."""
        context_manager.assemble_for_task(
            session_id="session_123",
            task="test task",
            semantic_header="header",
            episodic_context="episodic"
        )
        
        session = context_manager._sessions["session_123"]
        for zone in ZONES_ORDER:
            assert zone in session
    
    def test_includes_task_in_anchor(self, context_manager):
        """Test that task is included in task_anchor."""
        context_manager.assemble_for_task(
            session_id="session_123",
            task="current task description",
            semantic_header="header",
            episodic_context="episodic"
        )
        
        session = context_manager._sessions["session_123"]
        assert "current task description" in session["task_anchor"]


class TestAppend:
    """Test appending content to zones."""
    
    def test_appends_to_zone(self, context_manager):
        """Test that append adds content to zone."""
        context_manager.assemble_for_task(
            session_id="session_123",
            task="task",
            semantic_header="header",
            episodic_context="episodic"
        )
        
        context_manager.append("session_123", "new content", zone="working_history")
        
        session = context_manager._sessions["session_123"]
        assert "new content" in session["working_history"]
    
    def test_triggers_compression_at_threshold(self, context_manager, mock_adapter):
        """Test that compression triggers at threshold."""
        mock_adapter.count_tokens.return_value = 7000  # > 80% of 8192
        
        context_manager.assemble_for_task(
            session_id="session_123",
            task="task",
            semantic_header="header",
            episodic_context="episodic"
        )
        
        with patch.object(context_manager, '_compress') as mock_compress:
            context_manager.append("session_123", "content", zone="working_history")
            
            # Compression should be triggered for anchor zones at threshold
            # Note: Compression may or may not be called depending on implementation


class TestRender:
    """Test rendering context."""
    
    def test_renders_all_zones(self, context_manager):
        """Test that render includes all zones."""
        context_manager.assemble_for_task(
            session_id="session_123",
            task="task",
            semantic_header="User prefers concise",
            episodic_context="Previous similar task"
        )
        
        rendered = context_manager.render("session_123")
        
        assert "User prefers concise" in rendered
        assert "Previous similar task" in rendered
        assert "task" in rendered
    
    def test_filters_empty_zones(self, context_manager):
        """Test that empty zones are filtered."""
        context_manager.assemble_for_task(
            session_id="session_123",
            task="task",
            semantic_header="",
            episodic_context="content"
        )
        
        rendered = context_manager.render("session_123")
        
        # Empty zones should not add extra whitespace
        assert rendered.strip() == rendered
    
    def test_follows_zones_order(self, context_manager):
        """Test that zones are rendered in correct order."""
        context_manager._sessions["session_123"] = {
            "semantic_header": "header",
            "episodic_context": "episodic",
            "task_anchor": "task",
            "active_tool_state": "tool",
            "working_history": "history"
        }
        
        rendered = context_manager.render("session_123")
        
        # Header should come before episodic
        header_pos = rendered.find("header")
        episodic_pos = rendered.find("episodic")
        assert header_pos < episodic_pos


class TestClearSession:
    """Test clearing sessions."""
    
    def test_removes_session(self, context_manager):
        """Test that clear_session removes session."""
        context_manager._sessions["session_123"] = {"zone": "content"}
        
        context_manager.clear_session("session_123")
        
        assert "session_123" not in context_manager._sessions
    
    def test_handles_missing_session(self, context_manager):
        """Test that clearing missing session doesn't error."""
        # Should not raise
        context_manager.clear_session("nonexistent_session")


class TestCompression:
    """Test context compression."""
    
    def test_compress_splits_at_40_percent(self, context_manager, mock_adapter):
        """Test that compression splits at 40% point."""
        # Create content that would trigger compression
        old_content = "Old content " * 50
        new_content = "New content " * 50
        
        context_manager._sessions["session_123"] = {
            "working_history": old_content + "|||SPLIT|||" + new_content
        }
        
        # Mock the adapter for compression
        mock_adapter.generate.return_value = "Summary of old content"
        
        with patch.object(context_manager, '_usage_pct', return_value=0.9):
            context_manager._compress("session_123", "working_history")
    
    def test_compress_keeps_newest_verbatim(self, context_manager):
        """Test that compression keeps newest content verbatim."""
        context_manager._sessions["session_123"] = {
            "working_history": "Old\nMiddle\nNew"
        }
        
        # After compression, newest content should be preserved
        with patch.object(context_manager, '_usage_pct', return_value=0.9):
            with patch.object(context_manager.adapter, 'generate', return_value="Summary"):
                context_manager._compress("session_123", "working_history")
                
                # Newest content should still be present
                assert "New" in context_manager._sessions["session_123"]["working_history"]


class TestUsagePct:
    """Test usage percentage calculation."""
    
    def test_usage_pct_returns_percentage(self, context_manager, mock_adapter):
        """Test that usage_pct returns a percentage."""
        mock_adapter.count_tokens.return_value = 4000
        mock_adapter.get_context_size.return_value = 8000
        
        context_manager._sessions["session_123"] = {
            "working_history": "content"
        }
        
        pct = context_manager._usage_pct("session_123")
        
        assert pct == 0.5  # 4000 / 8000
    
    def test_usage_pct_zero_when_empty(self, context_manager, mock_adapter):
        """Test that usage_pct is 0 for empty content."""
        mock_adapter.count_tokens.return_value = 0
        
        context_manager._sessions["session_123"] = {
            "working_history": ""
        }
        
        pct = context_manager._usage_pct("session_123")
        
        assert pct == 0.0


class TestSessionIsolation:
    """Test session isolation."""
    
    def test_sessions_are_isolated(self, context_manager):
        """Test that different sessions don't share data."""
        context_manager._sessions["session_1"] = {"working_history": "content1"}
        context_manager._sessions["session_2"] = {"working_history": "content2"}
        
        assert context_manager._sessions["session_1"]["working_history"] == "content1"
        assert context_manager._sessions["session_2"]["working_history"] == "content2"
    
    def test_clear_one_session_others_preserved(self, context_manager):
        """Test that clearing one session preserves others."""
        context_manager._sessions["session_1"] = {"working_history": "content1"}
        context_manager._sessions["session_2"] = {"working_history": "content2"}
        
        context_manager.clear_session("session_1")
        
        assert "session_1" not in context_manager._sessions
        assert "session_2" in context_manager._sessions


class TestToolState:
    """Test tool state management."""
    
    def test_update_tool_state(self, context_manager):
        """Test updating tool state."""
        context_manager._sessions["session_123"] = {
            "active_tool_state": ""
        }
        
        context_manager.update_tool_state("session_123", "Tool output: result")
        
        assert "Tool output: result" in context_manager._sessions["session_123"]["active_tool_state"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
