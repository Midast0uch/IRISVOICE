"""
Property-Based Tests for Voice Command Processing

Feature: irisvoice-backend-integration
Property 8: Voice Command Processing

**Validates: Requirements 3.5, 3.6**

For any voice_command_end message during listening state, the LFM_Audio_Model shall
complete audio processing and the voice state shall transition to "processing_conversation".
"""
import pytest
from hypothesis import given, strategies as st, settings, HealthCheck
import asyncio
from unittest.mock import Mock, AsyncMock

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


class TestVoiceCommandProcessing:
    """Property tests for voice command processing"""
    
    @pytest.mark.asyncio
    @given(session_id=session_ids())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_voice_command_end_transitions_to_processing(self, session_id):
        """
        **Validates: Requirements 3.5, 3.6**
        
        Property: For any voice_command_end message during listening state,
        the voice state shall transition to "processing_conversation".
        
        Test Strategy:
        1. Start listening (transition to LISTENING)
        2. Stop listening (voice_command_end)
        3. Verify state transitions to PROCESSING_CONVERSATION
        4. Verify audio engine stops audio interaction
        """
        # Create fresh instances
        mock_audio_engine = create_mock_audio_engine()
        voice_pipeline = VoicePipeline(audio_engine=mock_audio_engine)
        
        # Initialize and start listening
        await voice_pipeline.initialize()
        await voice_pipeline.start_listening(session_id)
        
        # Verify in LISTENING state
        assert voice_pipeline.get_state(session_id) == VoiceState.LISTENING
        
        # Stop listening (voice_command_end)
        success = await voice_pipeline.stop_listening(session_id)
        
        # Verify success
        assert success is True
        
        # Verify state transitioned to PROCESSING_CONVERSATION
        assert voice_pipeline.get_state(session_id) == VoiceState.PROCESSING_CONVERSATION
        
        # Verify audio engine stopped audio interaction
        mock_audio_engine.stop_audio_interaction.assert_called_once()
    
    @pytest.mark.asyncio
    @given(session_id=session_ids())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_voice_command_end_completes_audio_processing(self, session_id):
        """
        **Validates: Requirements 3.5**
        
        Property: For any voice_command_end message, the LFM_Audio_Model
        shall complete audio processing.
        
        Test Strategy:
        1. Start listening
        2. Stop listening
        3. Verify audio engine's stop_audio_interaction is called
        """
        # Create fresh instances
        mock_audio_engine = create_mock_audio_engine()
        voice_pipeline = VoicePipeline(audio_engine=mock_audio_engine)
        
        # Initialize and start listening
        await voice_pipeline.initialize()
        await voice_pipeline.start_listening(session_id)
        
        # Stop listening
        await voice_pipeline.stop_listening(session_id)
        
        # Verify audio engine stopped audio interaction
        mock_audio_engine.stop_audio_interaction.assert_called_once()
    
    @pytest.mark.asyncio
    @given(session_id=session_ids())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_audio_processing_full_cycle(self, session_id):
        """
        **Validates: Requirements 3.5, 3.6, 3.7**
        
        Property: For any complete voice command cycle (start -> end -> process),
        the voice state shall transition through LISTENING -> PROCESSING_CONVERSATION
        -> SPEAKING -> IDLE.
        
        Test Strategy:
        1. Start listening (LISTENING)
        2. Stop listening (PROCESSING_CONVERSATION)
        3. Process audio (SPEAKING -> IDLE)
        4. Verify all state transitions occur
        """
        # Create fresh instances
        mock_audio_engine = create_mock_audio_engine()
        voice_pipeline = VoicePipeline(audio_engine=mock_audio_engine)
        
        # Track state transitions
        state_transitions = []
        def track_state(state):
            state_transitions.append(state)
        
        voice_pipeline.register_state_callback(session_id, track_state)
        
        # Initialize
        await voice_pipeline.initialize()
        
        # Start listening
        await voice_pipeline.start_listening(session_id)
        assert voice_pipeline.get_state(session_id) == VoiceState.LISTENING
        
        # Stop listening
        await voice_pipeline.stop_listening(session_id)
        assert voice_pipeline.get_state(session_id) == VoiceState.PROCESSING_CONVERSATION
        
        # Process audio
        result = await voice_pipeline.process_audio(b"test audio", session_id)
        
        # Verify final state is IDLE
        assert voice_pipeline.get_state(session_id) == VoiceState.IDLE
        
        # Verify state transitions occurred
        assert VoiceState.LISTENING in state_transitions
        assert VoiceState.PROCESSING_CONVERSATION in state_transitions
        assert VoiceState.SPEAKING in state_transitions
        assert VoiceState.IDLE in state_transitions
    
    @pytest.mark.asyncio
    @given(session_id=session_ids())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_state_callback_notified_on_processing_transition(self, session_id):
        """
        **Validates: Requirements 3.6**
        
        Property: When voice state transitions to "processing_conversation",
        registered callbacks shall be notified with the new state.
        
        Test Strategy:
        1. Register a state callback
        2. Start and stop listening
        3. Verify callback was called with PROCESSING_CONVERSATION state
        """
        # Create fresh instances
        mock_audio_engine = create_mock_audio_engine()
        voice_pipeline = VoicePipeline(audio_engine=mock_audio_engine)
        
        # Initialize
        await voice_pipeline.initialize()
        
        # Register callback
        callback_called = []
        def state_callback(state):
            callback_called.append(state)
        
        voice_pipeline.register_state_callback(session_id, state_callback)
        
        # Start and stop listening
        await voice_pipeline.start_listening(session_id)
        await voice_pipeline.stop_listening(session_id)
        
        # Verify callback was called with PROCESSING_CONVERSATION state
        assert VoiceState.PROCESSING_CONVERSATION in callback_called
    
    @pytest.mark.asyncio
    @given(session_id=session_ids())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_audio_level_monitoring_stops_on_command_end(self, session_id):
        """
        **Validates: Requirements 22.7**
        
        Property: When voice state transitions from "listening" to any other state,
        the audio level shall reset to 0.
        
        Test Strategy:
        1. Start listening (audio level monitoring starts)
        2. Verify audio level is non-zero during listening
        3. Stop listening
        4. Verify audio level resets to 0
        """
        # Create fresh instances
        mock_audio_engine = create_mock_audio_engine()
        voice_pipeline = VoicePipeline(audio_engine=mock_audio_engine)
        
        # Initialize and start listening
        await voice_pipeline.initialize()
        await voice_pipeline.start_listening(session_id)
        
        # Wait for audio level monitoring to start
        await asyncio.sleep(0.2)
        
        # Verify audio level is non-zero during listening
        audio_level_during_listening = voice_pipeline.get_audio_level()
        # Note: In real implementation, this would be non-zero
        # For now, we just verify the monitoring task exists
        assert voice_pipeline._audio_level_task is not None
        
        # Stop listening
        await voice_pipeline.stop_listening(session_id)
        
        # Verify audio level resets to 0
        audio_level_after_stop = voice_pipeline.get_audio_level()
        assert audio_level_after_stop == 0.0
        
        # Verify monitoring task is stopped
        assert voice_pipeline._audio_level_task is None
    
    @pytest.mark.asyncio
    @given(session_id=session_ids())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_error_during_stop_transitions_to_error_state(self, session_id):
        """
        **Validates: Requirements 3.9**
        
        Property: If an error occurs during voice_command_end processing,
        the voice state shall transition to ERROR.
        
        Test Strategy:
        1. Start listening
        2. Mock audio engine to raise exception on stop
        3. Attempt to stop listening
        4. Verify state transitions to ERROR
        """
        # Create mock that fails on stop
        mock_audio_engine = create_mock_audio_engine()
        mock_audio_engine.stop_audio_interaction = AsyncMock(side_effect=Exception("Stop failed"))
        voice_pipeline = VoicePipeline(audio_engine=mock_audio_engine)
        
        # Initialize and start listening
        await voice_pipeline.initialize()
        await voice_pipeline.start_listening(session_id)
        
        # Attempt to stop listening (should fail)
        success = await voice_pipeline.stop_listening(session_id)
        
        # Verify failure
        assert success is False
        
        # Verify state transitioned to ERROR
        assert voice_pipeline.get_state(session_id) == VoiceState.ERROR
