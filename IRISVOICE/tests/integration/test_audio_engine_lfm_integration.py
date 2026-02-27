"""
Integration tests for AudioEngine with LFM 2.5 Audio Model

These tests verify that AudioEngine correctly integrates with the LFM 2.5 audio model
and provides a simple interface for audio interaction.

**Validates: Requirements 11.1, 11.2, 12.1-12.7**
"""
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.voice.audio_engine import AudioEngine


class TestAudioEngineLFMIntegration:
    """
    Integration tests for AudioEngine with LFM 2.5 Audio Model
    
    These tests verify that:
    1. AudioEngine can initialize the LFM 2.5 audio model
    2. Audio interaction can start/stop
    3. Basic error handling works
    """
    
    @pytest.mark.asyncio
    async def test_audio_engine_initialization(self):
        """
        Test that AudioEngine can initialize the LFM 2.5 audio model.
        
        **Validates: Requirements 11.1, 11.2**
        """
        # Create mock LFM audio manager
        mock_lfm = MagicMock()
        mock_lfm.initialize = AsyncMock(return_value=None)
        
        # Create AudioEngine with mock
        engine = AudioEngine(lfm_audio_manager=mock_lfm)
        
        # Verify initial state
        assert not engine._is_initialized
        assert not engine._is_running
        
        # Initialize
        result = await engine.initialize()
        
        # Verify initialization succeeded
        assert result is True
        assert engine._is_initialized
        mock_lfm.initialize.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_audio_engine_initialization_failure(self):
        """
        Test that AudioEngine handles initialization failures gracefully.
        
        **Validates: Requirements 11.1, 11.2**
        """
        # Create mock LFM audio manager that fails
        mock_lfm = MagicMock()
        mock_lfm.initialize = AsyncMock(side_effect=Exception("Initialization failed"))
        
        # Create AudioEngine with mock
        engine = AudioEngine(lfm_audio_manager=mock_lfm)
        
        # Initialize (should fail)
        result = await engine.initialize()
        
        # Verify initialization failed
        assert result is False
        assert not engine._is_initialized
    
    @pytest.mark.asyncio
    async def test_start_audio_interaction(self):
        """
        Test that AudioEngine can start audio interaction.
        
        **Validates: Requirements 11.1, 11.2, 12.1-12.7**
        """
        # Create mock LFM audio manager
        mock_lfm = MagicMock()
        mock_lfm.initialize = AsyncMock(return_value=None)
        
        # Create and initialize AudioEngine
        engine = AudioEngine(lfm_audio_manager=mock_lfm)
        await engine.initialize()
        
        # Start audio interaction
        result = await engine.start_audio_interaction()
        
        # Verify interaction started
        assert result is True
        assert engine._is_running
    
    @pytest.mark.asyncio
    async def test_start_audio_interaction_without_initialization(self):
        """
        Test that AudioEngine rejects starting audio interaction without initialization.
        
        **Validates: Requirements 11.1, 11.2**
        """
        # Create mock LFM audio manager
        mock_lfm = MagicMock()
        
        # Create AudioEngine (don't initialize)
        engine = AudioEngine(lfm_audio_manager=mock_lfm)
        
        # Try to start audio interaction
        result = await engine.start_audio_interaction()
        
        # Verify interaction failed
        assert result is False
        assert not engine._is_running
    
    @pytest.mark.asyncio
    async def test_stop_audio_interaction(self):
        """
        Test that AudioEngine can stop audio interaction.
        
        **Validates: Requirements 11.1, 11.2, 12.1-12.7**
        """
        # Create mock LFM audio manager
        mock_lfm = MagicMock()
        mock_lfm.initialize = AsyncMock(return_value=None)
        
        # Create and initialize AudioEngine
        engine = AudioEngine(lfm_audio_manager=mock_lfm)
        await engine.initialize()
        await engine.start_audio_interaction()
        
        # Stop audio interaction
        await engine.stop_audio_interaction()
        
        # Verify interaction stopped
        assert not engine._is_running
    
    @pytest.mark.asyncio
    async def test_process_audio(self):
        """
        Test that AudioEngine can process audio through LFM 2.5 audio model.
        
        **Validates: Requirements 12.1-12.7**
        """
        # Create mock LFM audio manager
        mock_lfm = MagicMock()
        mock_lfm.initialize = AsyncMock(return_value=None)
        mock_lfm.process_audio_stream = AsyncMock(return_value=b"response_audio")
        
        # Create and initialize AudioEngine
        engine = AudioEngine(lfm_audio_manager=mock_lfm)
        await engine.initialize()
        
        # Process audio
        audio_data = b"test_audio_data"
        response = await engine.process_audio(audio_data)
        
        # Verify audio was processed
        assert response == b"response_audio"
        mock_lfm.process_audio_stream.assert_called_once_with(audio_data)
    
    @pytest.mark.asyncio
    async def test_process_audio_without_initialization(self):
        """
        Test that AudioEngine handles processing audio without initialization.
        
        **Validates: Requirements 11.1, 11.2**
        """
        # Create mock LFM audio manager
        mock_lfm = MagicMock()
        
        # Create AudioEngine (don't initialize)
        engine = AudioEngine(lfm_audio_manager=mock_lfm)
        
        # Try to process audio
        audio_data = b"test_audio_data"
        response = await engine.process_audio(audio_data)
        
        # Verify processing failed gracefully
        assert response == b""
    
    @pytest.mark.asyncio
    async def test_process_audio_error_handling(self):
        """
        Test that AudioEngine handles audio processing errors gracefully.
        
        **Validates: Requirements 12.1-12.7**
        """
        # Create mock LFM audio manager that fails
        mock_lfm = MagicMock()
        mock_lfm.initialize = AsyncMock(return_value=None)
        mock_lfm.process_audio_stream = AsyncMock(side_effect=Exception("Processing failed"))
        
        # Create and initialize AudioEngine
        engine = AudioEngine(lfm_audio_manager=mock_lfm)
        await engine.initialize()
        
        # Try to process audio
        audio_data = b"test_audio_data"
        response = await engine.process_audio(audio_data)
        
        # Verify error was handled gracefully
        assert response == b""
    
    @pytest.mark.asyncio
    async def test_get_status(self):
        """
        Test that AudioEngine returns correct status information.
        
        **Validates: Requirements 11.1, 11.2**
        """
        # Create mock LFM audio manager
        mock_lfm = MagicMock()
        mock_lfm.initialize = AsyncMock(return_value=None)
        
        # Create AudioEngine
        engine = AudioEngine(lfm_audio_manager=mock_lfm)
        
        # Get status before initialization
        status = engine.get_status()
        assert status["is_initialized"] is False
        assert status["is_running"] is False
        assert status["lfm_audio_available"] is True
        
        # Initialize
        await engine.initialize()
        
        # Get status after initialization
        status = engine.get_status()
        assert status["is_initialized"] is True
        assert status["is_running"] is False
        
        # Start audio interaction
        await engine.start_audio_interaction()
        
        # Get status while running
        status = engine.get_status()
        assert status["is_initialized"] is True
        assert status["is_running"] is True
    
    @pytest.mark.asyncio
    async def test_multiple_initialization_calls(self):
        """
        Test that AudioEngine handles multiple initialization calls gracefully.
        
        **Validates: Requirements 11.1, 11.2**
        """
        # Create mock LFM audio manager
        mock_lfm = MagicMock()
        mock_lfm.initialize = AsyncMock(return_value=None)
        
        # Create AudioEngine
        engine = AudioEngine(lfm_audio_manager=mock_lfm)
        
        # Initialize multiple times
        result1 = await engine.initialize()
        result2 = await engine.initialize()
        result3 = await engine.initialize()
        
        # Verify all succeeded
        assert result1 is True
        assert result2 is True
        assert result3 is True
        
        # Verify LFM was only initialized once
        assert mock_lfm.initialize.call_count == 1
    
    @pytest.mark.asyncio
    async def test_start_stop_cycle(self):
        """
        Test that AudioEngine can start and stop audio interaction multiple times.
        
        **Validates: Requirements 11.1, 11.2, 12.1-12.7**
        """
        # Create mock LFM audio manager
        mock_lfm = MagicMock()
        mock_lfm.initialize = AsyncMock(return_value=None)
        
        # Create and initialize AudioEngine
        engine = AudioEngine(lfm_audio_manager=mock_lfm)
        await engine.initialize()
        
        # Start/stop cycle 1
        result1 = await engine.start_audio_interaction()
        assert result1 is True
        assert engine._is_running
        
        await engine.stop_audio_interaction()
        assert not engine._is_running
        
        # Start/stop cycle 2
        result2 = await engine.start_audio_interaction()
        assert result2 is True
        assert engine._is_running
        
        await engine.stop_audio_interaction()
        assert not engine._is_running


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
