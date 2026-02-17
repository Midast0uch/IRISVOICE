
import pytest
import asyncio
import json
import tempfile
import os
from pathlib import Path
from datetime import datetime, timezone

# Import the debug tools
from backend.debug.session_replay import SessionReplay
from backend.debug.state_inspector import StateInspector
from backend.debug.performance_metrics import PerformanceMonitor, performance_monitor

# Import session management for testing
from backend.sessions.session_manager import SessionManager
from backend.state_manager import StateManager

class TestSessionReplay:
    """Test cases for SessionReplay functionality."""

    def test_session_replay_initialization(self):
        """Test that SessionReplay initializes correctly."""
        session_id = "test_session_123"
        replay = SessionReplay(session_id)
        
        assert replay.session_id == session_id
        assert not replay.is_recording
        assert replay.events == []
        assert replay.start_time is None

    def test_start_and_stop_recording(self):
        """Test starting and stopping recording."""
        session_id = "test_session_123"
        replay = SessionReplay(session_id)
        
        # Start recording
        replay.start_recording()
        assert replay.is_recording
        assert replay.start_time is not None
        assert len(replay.events) == 1  # session_start event
        assert replay.events[0]["event_type"] == "session_start"
        
        # Stop recording
        replay.stop_recording()
        assert not replay.is_recording
        assert len(replay.events) == 2  # session_start + session_end
        assert replay.events[-1]["event_type"] == "session_end"

    def test_add_event(self):
        """Test adding events to the recording."""
        session_id = "test_session_123"
        replay = SessionReplay(session_id)
        
        replay.start_recording()
        
        # Add some events
        replay.add_event("user_action", {"action": "click", "target": "button"})
        replay.add_event("state_change", {"field": "status", "value": "active"})
        
        assert len(replay.events) == 3  # session_start + 2 custom events
        assert replay.events[1]["event_type"] == "user_action"
        assert replay.events[1]["payload"]["action"] == "click"
        assert replay.events[2]["event_type"] == "state_change"
        assert replay.events[2]["payload"]["field"] == "status"

    def test_save_and_load_recording(self):
        """Test saving and loading session recordings."""
        session_id = "test_session_123"
        replay = SessionReplay(session_id)
        
        # Create a recording
        replay.start_recording()
        replay.add_event("test_event", {"data": "test"})
        replay.stop_recording()
        
        # Save the recording
        with tempfile.TemporaryDirectory() as temp_dir:
            replay.recording_dir = Path(temp_dir)
            saved_path = replay.save_recording()
            
            assert saved_path is not None
            assert saved_path.exists()
            
            # Load the recording
            loaded_data = SessionReplay.load_recording(saved_path)
            assert loaded_data is not None
            assert loaded_data["session_id"] == session_id
            assert loaded_data["event_count"] == 3  # session_start + test_event + session_end
            assert len(loaded_data["events"]) == 3

    def test_recording_without_start(self):
        """Test that events aren't recorded without starting."""
        session_id = "test_session_123"
        replay = SessionReplay(session_id)
        
        # Try to add event without starting
        replay.add_event("test_event", {"data": "test"})
        assert len(replay.events) == 0
        
        # Try to stop without starting
        replay.stop_recording()
        assert len(replay.events) == 0


class TestStateInspector:
    """Test cases for StateInspector functionality."""

    @pytest.fixture
    def session_manager(self):
        manager = SessionManager()
        yield manager
        # Properly shutdown the session manager's async tasks
        asyncio.run(manager.shutdown())

    @pytest.fixture
    def state_manager(self, session_manager):
        return StateManager(session_manager)

    @pytest.fixture
    def state_inspector(self, session_manager, state_manager):
        return StateInspector(session_manager, state_manager)

    @pytest.mark.asyncio
    async def test_get_session_state(self, state_inspector: StateInspector, state_manager: StateManager, session_manager: SessionManager):
        """Test getting session state."""
        session_id = await session_manager.create_session()
        await state_manager.update_field(session_id, "test_subnode", "test_key", "test_value")
        
        state = await state_inspector.get_session_state(session_id)
        assert state is not None
        assert state['field_values']["test_subnode"]["test_key"] == "test_value"

    @pytest.mark.asyncio
    async def test_get_all_sessions_summary(self, state_inspector: StateInspector, session_manager: SessionManager):
        """Test getting summary of all sessions."""
        # Create multiple sessions
        session1 = await session_manager.create_session()
        session2 = await session_manager.create_session()
        
        summary = await state_inspector.get_all_sessions_summary()
        assert len(summary) == 2
        assert session1 in summary
        assert session2 in summary
        
        # Check summary structure
        for session_id, info in summary.items():
            assert "session_type" in info
            assert "created_at" in info
            assert "last_accessed_at" in info
            assert "is_active" in info
            assert "memory_usage" in info

    @pytest.mark.asyncio
    async def test_compare_session_states(self, state_inspector: StateInspector, state_manager: StateManager, session_manager: SessionManager):
        """Test comparing two session states."""
        session1 = await session_manager.create_session()
        session2 = await session_manager.create_session()
        
        # Set different values in each session
        await state_manager.update_field(session1, "test_field", "value", "session1_value")
        await state_manager.update_field(session2, "test_field", "value", "session2_value")
        
        comparison = await state_inspector.compare_session_states(session1, session2)
        assert "differences" in comparison
        assert comparison["total_differences"] > 0

    @pytest.mark.asyncio
    async def test_query_state(self, state_inspector: StateInspector, state_manager: StateManager, session_manager: SessionManager):
        """Test querying specific state paths."""
        session_id = await session_manager.create_session()
        await state_manager.update_field(session_id, "test_subnode", "test_key", "test_value")
        
        # Query the nested value
        result = await state_inspector.query_state(session_id, "field_values.test_subnode.test_key")
        assert result == "test_value"
        
        # Query non-existent path
        result = await state_inspector.query_state(session_id, "nonexistent.path")
        assert result is None

    @pytest.mark.asyncio
    async def test_export_session_state(self, state_inspector: StateInspector, state_manager: StateManager, session_manager: SessionManager):
        """Test exporting session state to file."""
        session_id = await session_manager.create_session()
        await state_manager.update_field(session_id, "test_field", "value", "test_value")
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_path = f.name
        
        try:
            success = await state_inspector.export_session_state(session_id, temp_path)
            assert success is True
            
            # Verify the exported file
            with open(temp_path, 'r') as f:
                exported_state = json.load(f)
            assert exported_state['field_values']["test_field"]["value"] == "test_value"
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


class TestPerformanceMonitor:
    """Test cases for PerformanceMonitor functionality."""

    @pytest.fixture
    def performance_monitor(self):
        monitor = PerformanceMonitor(collection_interval=0.01)  # Fast interval for testing
        yield monitor
        asyncio.run(monitor.stop())

    @pytest.fixture
    def session_manager(self):
        manager = SessionManager()
        yield manager
        asyncio.run(manager.shutdown())

    @pytest.fixture
    def state_manager(self, session_manager):
        return StateManager(session_manager)

    @pytest.mark.asyncio
    async def test_performance_monitor_initialization(self, performance_monitor: PerformanceMonitor):
        """Test that PerformanceMonitor initializes correctly."""
        assert not performance_monitor.is_running
        assert performance_monitor.metrics == []
        assert performance_monitor.collection_interval == 0.01

    @pytest.mark.asyncio
    async def test_start_and_stop_monitoring(self, performance_monitor: PerformanceMonitor):
        """Test starting and stopping performance monitoring."""
        # Start monitoring
        await performance_monitor.start()
        assert performance_monitor.is_running
        assert performance_monitor.start_time is not None
        
        # Let it collect some metrics
        await asyncio.sleep(0.1)
        
        # Stop monitoring
        await performance_monitor.stop()
        assert not performance_monitor.is_running

    @pytest.mark.asyncio
    async def test_metric_collection(self, performance_monitor: PerformanceMonitor):
        """Test that metrics are being collected."""
        await performance_monitor.start()
        
        # Let it collect some metrics
        await asyncio.sleep(0.1)
        
        # Check that metrics were collected
        assert len(performance_monitor.metrics) > 0
        
        # Check for expected metric types
        metric_types = [m.metric_type for m in performance_monitor.metrics]
        assert "cpu_usage" in metric_types
        assert "memory_usage" in metric_types

    @pytest.mark.asyncio
    async def test_custom_metrics(self, performance_monitor: PerformanceMonitor):
        """Test adding custom metrics."""
        performance_monitor.add_metric("custom_metric", 42.0, {"test": "data"})
        
        assert len(performance_monitor.metrics) == 1
        metric = performance_monitor.metrics[0]
        assert metric.metric_type == "custom_metric"
        assert metric.value == 42.0
        assert metric.metadata["test"] == "data"

    @pytest.mark.asyncio
    async def test_get_metrics_filtering(self, performance_monitor: PerformanceMonitor):
        """Test filtering metrics by type."""
        # Add some custom metrics
        performance_monitor.add_metric("custom1", 1.0)
        performance_monitor.add_metric("custom2", 2.0)
        performance_monitor.add_metric("custom1", 3.0)
        
        # Filter by type
        custom1_metrics = performance_monitor.get_metrics(metric_type="custom1")
        assert len(custom1_metrics) == 2
        assert all(m.metric_type == "custom1" for m in custom1_metrics)

    @pytest.mark.asyncio
    async def test_get_summary(self, performance_monitor: PerformanceMonitor):
        """Test getting performance summary."""
        performance_monitor.add_metric("cpu_usage", 50.0)
        performance_monitor.add_metric("cpu_usage", 60.0)
        performance_monitor.add_metric("memory_usage", 70.0)
        
        summary = performance_monitor.get_summary()
        assert summary["total_metrics"] == 3
        assert "cpu_usage" in summary["metric_types"]
        assert "memory_usage" in summary["metric_types"]
        assert summary["avg_cpu_usage"] == 55.0  # (50 + 60) / 2
        assert summary["avg_memory_usage"] == 70.0

    @pytest.mark.asyncio
    async def test_export_metrics(self, performance_monitor: PerformanceMonitor):
        """Test exporting metrics to file."""
        performance_monitor.add_metric("test_metric", 100.0, {"test": "data"})
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_path = f.name
        
        try:
            success = performance_monitor.export_metrics(temp_path)
            assert success is True
            
            # Verify the exported file
            with open(temp_path, 'r') as f:
                exported_data = json.load(f)
            assert "metadata" in exported_data
            assert "metrics" in exported_data
            assert len(exported_data["metrics"]) == 1
            assert exported_data["metrics"][0]["metric_type"] == "test_metric"
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_application_metrics_with_session_manager(self, session_manager, state_manager):
        """Test application-specific metrics when session manager is provided."""
        monitor = PerformanceMonitor(
            collection_interval=0.01,
            session_manager=session_manager,
            state_manager=state_manager
        )
        
        await monitor.start()
        
        # Create a session
        session_id = await session_manager.create_session()
        
        # Let it collect some metrics
        await asyncio.sleep(0.1)
        
        # Check for application metrics
        metric_types = [m.metric_type for m in monitor.metrics]
        assert "active_sessions" in metric_types
        assert "session_memory" in metric_types
        assert "total_session_memory" in metric_types
        
        await monitor.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
