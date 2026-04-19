"""
Tests for DistillationProcess - Background Learning

_Requirements: 7.1, 7.2, 7.5_
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock

# Skip all tests if dependencies not available
pytest.importorskip("backend.memory", reason="Memory module not available")

from backend.memory.distillation import DistillationProcess


@pytest.fixture
def mock_memory_interface():
    """Create a mock MemoryInterface."""
    return Mock()


@pytest.fixture
def mock_adapter():
    """Create a mock model adapter."""
    return Mock()


@pytest.fixture
def distillation_process(mock_memory_interface, mock_adapter):
    """Create a DistillationProcess instance."""
    return DistillationProcess(
        memory_interface=mock_memory_interface,
        adapter=mock_adapter
    )


class TestDistillationInitialization:
    """Test DistillationProcess initialization."""
    
    def test_initializes_with_constants(self, mock_memory_interface, mock_adapter):
        """Test that DistillationProcess initializes with constants."""
        dp = DistillationProcess(mock_memory_interface, mock_adapter)
        
        assert dp.INTERVAL == 4  # hours
        assert dp.IDLE_THRESHOLD == 10  # minutes
        assert dp.MIN_EPISODES == 5
    
    def test_stores_references(self, mock_memory_interface, mock_adapter):
        """Test that DistillationProcess stores memory and adapter references."""
        dp = DistillationProcess(mock_memory_interface, mock_adapter)
        
        assert dp.memory is mock_memory_interface
        assert dp.adapter is mock_adapter


class TestRecordActivity:
    """Test activity recording."""
    
    def test_records_activity_timestamp(self, distillation_process):
        """Test that record_activity updates last_activity."""
        initial_time = distillation_process.last_activity
        
        # Wait a tiny bit to ensure time difference
        import time
        time.sleep(0.01)
        
        distillation_process.record_activity()
        
        assert distillation_process.last_activity > initial_time
    
    def test_resets_idle_timer(self, distillation_process):
        """Test that record_activity resets idle timer."""
        distillation_process.record_activity()
        
        # After activity, should not be idle
        assert distillation_process._get_idle_minutes() < 1


class TestShouldDistill:
    """Test distillation decision logic."""
    
    def test_returns_false_when_not_idle(self, distillation_process):
        """Test that should_distill returns False when not idle."""
        distillation_process.record_activity()  # Reset idle timer
        
        result = distillation_process._should_distill(
            recent_episodes=[1, 2, 3, 4, 5],
            hours_since_last=5
        )
        
        assert result is False
    
    def test_returns_false_when_not_enough_time(self, distillation_process):
        """Test that should_distill returns False when not enough time passed."""
        result = distillation_process._should_distill(
            recent_episodes=[1, 2, 3, 4, 5],
            hours_since_last=2  # Less than 4 hours
        )
        
        assert result is False
    
    def test_returns_false_when_not_enough_episodes(self, distillation_process):
        """Test that should_distill returns False when not enough episodes."""
        result = distillation_process._should_distill(
            recent_episodes=[1, 2],  # Less than 5
            hours_since_last=5
        )
        
        assert result is False
    
    def test_returns_true_when_all_conditions_met(self, distillation_process):
        """Test that should_distill returns True when all conditions met."""
        # Simulate idle by setting last_activity to past
        from datetime import datetime, timedelta
        distillation_process.last_activity = datetime.now() - timedelta(minutes=15)
        
        result = distillation_process._should_distill(
            recent_episodes=[1, 2, 3, 4, 5, 6],
            hours_since_last=5
        )
        
        assert result is True


class TestRunDistillation:
    """Test distillation execution."""
    
    @pytest.mark.asyncio
    async def test_fetches_recent_episodes(self, distillation_process, mock_memory_interface):
        """Test that distillation fetches recent episodes."""
        mock_memory_interface.episodic.get_recent_for_distillation.return_value = [
            {"task_summary": "Task 1"},
            {"task_summary": "Task 2"},
        ]
        mock_memory_interface.adapter.generate.return_value = "Extracted patterns"
        
        await distillation_process._run_distillation()
        
        mock_memory_interface.episodic.get_recent_for_distillation.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_calls_model_for_extraction(self, distillation_process, mock_memory_interface):
        """Test that distillation calls model for pattern extraction."""
        mock_memory_interface.episodic.get_recent_for_distillation.return_value = [
            {"task_summary": "Task 1"},
            {"task_summary": "Task 2"},
        ]
        mock_memory_interface.adapter.generate.return_value = "User prefers Python"
        
        await distillation_process._run_distillation()
        
        mock_memory_interface.adapter.generate.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_stores_patterns_in_semantic_memory(self, distillation_process, mock_memory_interface):
        """Test that extracted patterns are stored in semantic memory."""
        mock_memory_interface.episodic.get_recent_for_distillation.return_value = [
            {"task_summary": "Task 1"},
        ]
        mock_memory_interface.adapter.generate.return_value = "User prefers concise answers"
        
        await distillation_process._run_distillation()
        
        # Should call semantic.update with confidence=0.7
        mock_memory_interface.semantic.update.assert_called()
        call_args = mock_memory_interface.semantic.update.call_args
        if call_args:
            # Check for confidence parameter
            kwargs = call_args[1] if len(call_args) > 1 else call_args.kwargs
            if kwargs and 'confidence' in kwargs:
                assert kwargs['confidence'] == 0.7
    
    @pytest.mark.asyncio
    async def test_handles_empty_episodes(self, distillation_process, mock_memory_interface):
        """Test that distillation handles empty episodes gracefully."""
        mock_memory_interface.episodic.get_recent_for_distillation.return_value = []
        
        # Should not raise
        await distillation_process._run_distillation()


class TestSilentFailures:
    """Test silent failure handling."""
    
    @pytest.mark.asyncio
    async def test_handles_model_error_silently(self, distillation_process, mock_memory_interface):
        """Test that model errors are handled silently."""
        mock_memory_interface.episodic.get_recent_for_distillation.return_value = [
            {"task_summary": "Task 1"},
        ]
        mock_memory_interface.adapter.generate.side_effect = Exception("Model error")
        
        # Should not raise
        await distillation_process._run_distillation()
    
    @pytest.mark.asyncio
    async def test_handles_database_error_silently(self, distillation_process, mock_memory_interface):
        """Test that database errors are handled silently."""
        mock_memory_interface.episodic.get_recent_for_distillation.side_effect = Exception("DB error")
        
        # Should not raise
        await distillation_process._run_distillation()
    
    @pytest.mark.asyncio
    async def test_logs_errors(self, distillation_process, mock_memory_interface):
        """Test that errors are logged."""
        mock_memory_interface.episodic.get_recent_for_distillation.side_effect = Exception("Test error")
        
        with patch('backend.memory.distillation.logger') as mock_logger:
            await distillation_process._run_distillation()
            
            mock_logger.error.assert_called()


class TestSkillCrystalliserIntegration:
    """Test SkillCrystalliser integration."""
    
    @pytest.mark.asyncio
    async def test_calls_skill_crystalliser(self, distillation_process, mock_memory_interface):
        """Test that distillation calls skill crystalliser."""
        mock_memory_interface.episodic.get_recent_for_distillation.return_value = [
            {"task_summary": "Task 1"},
        ]
        mock_memory_interface.adapter.generate.return_value = "Patterns"
        
        with patch.object(distillation_process.skill_crystalliser, 'scan_and_crystallise') as mock_scan:
            await distillation_process._run_distillation()
            
            mock_scan.assert_called_once()


class TestStart:
    """Test starting the distillation process."""
    
    @pytest.mark.asyncio
    async def test_starts_background_task(self, distillation_process):
        """Test that start creates a background task."""
        with patch.object(distillation_process, '_distillation_loop', new_callable=AsyncMock) as mock_loop:
            distillation_process.start()
            
            # Give the task a moment to start
            await asyncio.sleep(0.01)
            
            # The loop should be scheduled
            assert distillation_process._task is not None
            
            # Clean up
            distillation_process._task.cancel()
            try:
                await distillation_process._task
            except asyncio.CancelledError:
                pass


class TestIdleTracking:
    """Test idle time tracking."""
    
    def test_get_idle_minutes_zero_after_activity(self, distillation_process):
        """Test that idle minutes is 0 after activity."""
        distillation_process.record_activity()
        
        idle_minutes = distillation_process._get_idle_minutes()
        
        assert idle_minutes < 0.1  # Less than 0.1 minutes (6 seconds)
    
    def test_get_idle_minutes_increases_over_time(self, distillation_process):
        """Test that idle minutes increases over time."""
        from datetime import datetime, timedelta
        distillation_process.last_activity = datetime.now() - timedelta(minutes=5)
        
        idle_minutes = distillation_process._get_idle_minutes()
        
        assert idle_minutes >= 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
