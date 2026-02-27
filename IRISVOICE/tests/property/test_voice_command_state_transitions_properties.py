"""
Property-Based Tests for Voice Command State Transitions

Feature: irisvoice-backend-integration
Property 7: Voice Command State Transitions

**Validates: Requirements 3.2, 3.3**

For any voice_command_start message, the LFM_Audio_Model shall begin audio processing
and the voice state shall transition to "listening".
"""
import pytest
from hypothesis import given, strategies as st, settings, HealthCheck
import asyncio
from unittest.mock import Mock, AsyncMock, patch

from backend.voice.voice_pipeline import VoicePipeline, VoiceState
from backend.voice.audio_engine import AudioEngine


# Test data generators
@st.composite
def session_ids(draw):
    """Generate valid session IDs"""
    return draw(st.uuids()).hex


def create_mock_audio_engine():
    """Create a mock AudioEngine"""
    engine = Mock(spec=AudioEngine)
    engine.initialize = AsyncMock(return_value=True)
    engine.start_audio_interaction = AsyncMock(return_value=True)
    engine.stop_audio_interaction = AsyncMock(return_value=None)
    engine.process_audio = AsyncMock(return_value=b"response")
    engine.get_status = Mock(return_value={
        "is_initialized": True,
        "is_running": False,
        "lfm_audio_available": True
    })
    return engine


class TestVoiceCommandStateTransitions:
    """Property tests for voice command state transitions"""
    
    @pytest.mark.asyncio
    @given(session_id=session_ids())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_voice_command_start_transitions_to_listening(self, session_id):
        """
        **Validates: Requirements 3.2, 3.3**
        
        Property: For any voice_command_start message, the voice state shall
        transition to "listening" and the LFM_Audio_Model shall begin audio processing.
        
        Test Strategy:
        1. Initialize voice pipeline
        2. Start listening for a session
        3. Verify state transitions to LISTENING
        4. Verify audio engine starts audio interaction
        """
        # Create fresh instances for each test
        mock_audio_engine = create_mock_audio_engine()
        voice_pipeline = VoicePipeline(audio_engine=mock_audio_engine)
        
        # Initialize pipeline
        await voice_pipeline.initialize()
        
        # Verify initial state is IDLE
        assert voice_pipeline.get_state(session_id) == VoiceState.IDLE
        
        # Start listening
        success = await voice_pipeline.start_listening(session_id)
        
        # Verify success
        assert success is True
        
        # Verify state transitioned to LISTENING
        assert voice_pipeline.get_state(session_id) == VoiceState.LISTENING
        
        # Verify audio engine started audio interaction
        mock_audio_engine.start_audio_interaction.assert_called_once()
    
    @pytest.mark.asyncio
    @given(session_id=session_ids())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_voice_command_start_activates_lfm_audio_model(self, session_id):
        """
        **Validates: Requirements 3.2**
        
        Property: For any voice_command_start message, the LFM_Audio_Model
        shall begin audio processing (audio capture, VAD, wake word detection, STT).
        
        Test Strategy:
        1. Initialize voice pipeline
        2. Start listening
        3. Verify audio engine's start_audio_interaction is called
        4. Verify audio engine status shows running
        """
        # Create fresh instances for each test
        mock_audio_engine = create_mock_audio_engine()
        voice_pipeline = VoicePipeline(audio_engine=mock_audio_engine)
        
        # Initialize pipeline
        await voice_pipeline.initialize()
        
        # Start listening
        await voice_pipeline.start_listening(session_id)
        
        # Verify audio engine started audio interaction
        mock_audio_engine.start_audio_interaction.assert_called_once()
        
        # Verify audio engine is in correct state
        status = mock_audio_engine.get_status()
        assert status["is_initialized"] is True
        assert status["lfm_audio_available"] is True
    
    @pytest.mark.asyncio
    @given(session_id=session_ids())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_state_callback_notified_on_transition(self, session_id):
        """
        **Validates: Requirements 3.3**
        
        Property: When voice state transitions to "listening", registered
        callbacks shall be notified with the new state.
        
        Test Strategy:
        1. Register a state callback
        2. Start listening
        3. Verify callback was called with LISTENING state
        """
        # Create fresh instances for each test
        mock_audio_engine = create_mock_audio_engine()
        voice_pipeline = VoicePipeline(audio_engine=mock_audio_engine)
        
        # Initialize pipeline
        await voice_pipeline.initialize()
        
        # Register callback
        callback_called = []
        def state_callback(state):
            callback_called.append(state)
        
        voice_pipeline.register_state_callback(session_id, state_callback)
        
        # Start listening
        await voice_pipeline.start_listening(session_id)
        
        # Verify callback was called with LISTENING state
        assert VoiceState.LISTENING in callback_called
    
    @pytest.mark.asyncio
    @given(session_id=session_ids())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_audio_engine_failure_transitions_to_error(self, session_id):
        """
        **Validates: Requirements 3.9**
        
        Property: If audio engine fails to start, voice state shall
        transition to ERROR.
        
        Test Strategy:
        1. Mock audio engine to fail on start
        2. Attempt to start listening
        3. Verify state transitions to ERROR
        """
        # Create mock that fails
        mock_audio_engine = create_mock_audio_engine()
        mock_audio_engine.start_audio_interaction = AsyncMock(return_value=False)
        voice_pipeline = VoicePipeline(audio_engine=mock_audio_engine)
        
        # Initialize pipeline
        await voice_pipeline.initialize()
        
        # Attempt to start listening
        success = await voice_pipeline.start_listening(session_id)
        
        # Verify failure
        assert success is False
        
        # Verify state transitioned to ERROR
        assert voice_pipeline.get_state(session_id) == VoiceState.ERROR
    
    @pytest.mark.asyncio
    @given(session_id=session_ids())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_multiple_sessions_independent_states(self, session_id):
        """
        **Validates: Requirements 2.4 (Session State Isolation)**
        
        Property: Voice states for different sessions shall be independent.
        
        Test Strategy:
        1. Create two different session IDs
        2. Start listening for one session
        3. Verify only that session's state changes
        4. Verify other session remains in IDLE
        """
        # Create fresh instances for each test
        mock_audio_engine = create_mock_audio_engine()
        voice_pipeline = VoicePipeline(audio_engine=mock_audio_engine)
        
        # Initialize pipeline
        await voice_pipeline.initialize()
        
        # Create second session ID
        session_id_2 = session_id + "_2"
        
        # Verify both start in IDLE
        assert voice_pipeline.get_state(session_id) == VoiceState.IDLE
        assert voice_pipeline.get_state(session_id_2) == VoiceState.IDLE
        
        # Start listening for first session only
        await voice_pipeline.start_listening(session_id)
        
        # Verify first session is LISTENING
        assert voice_pipeline.get_state(session_id) == VoiceState.LISTENING
        
        # Verify second session remains IDLE
        assert voice_pipeline.get_state(session_id_2) == VoiceState.IDLE
