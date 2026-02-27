"""
Property-Based Tests for Audio Level Updates

Feature: irisvoice-backend-integration
Property 52: Audio Level Updates

**Validates: Requirements 22.1, 22.3**

For any audio capture during listening state, the LFM_Audio_Model shall send
audio level updates as normalized values between 0.0 and 1.0.
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


class TestAudioLevelUpdates:
    """Property tests for audio level updates"""
    
    @pytest.mark.asyncio
    @given(session_id=session_ids())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_audio_level_normalized_range(self, session_id):
        """
        **Validates: Requirements 22.1, 22.3**
        
        Property: For any audio capture during listening state, audio level
        updates shall be normalized values between 0.0 and 1.0.
        
        Test Strategy:
        1. Start listening
        2. Wait for audio level updates
        3. Verify all audio levels are in range [0.0, 1.0]
        """
        # Create fresh instances
        mock_audio_engine = create_mock_audio_engine()
        voice_pipeline = VoicePipeline(audio_engine=mock_audio_engine)
        
        # Track audio levels
        audio_levels = []
        def track_audio_level(level):
            audio_levels.append(level)
        
        voice_pipeline.register_audio_level_callback(session_id, track_audio_level)
        
        # Initialize and start listening
        await voice_pipeline.initialize()
        await voice_pipeline.start_listening(session_id)
        
        # Wait for audio level updates (monitoring runs every 100ms)
        await asyncio.sleep(0.5)
        
        # Stop listening
        await voice_pipeline.stop_listening(session_id)
        
        # Verify audio levels were received
        assert len(audio_levels) > 0
        
        # Verify all audio levels are in range [0.0, 1.0]
        for level in audio_levels:
            assert 0.0 <= level <= 1.0, f"Audio level {level} out of range [0.0, 1.0]"
    
    @pytest.mark.asyncio
    @given(session_id=session_ids())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_audio_level_updates_during_listening(self, session_id):
        """
        **Validates: Requirements 22.1**
        
        Property: Audio level updates shall only be sent during listening state.
        
        Test Strategy:
        1. Register audio level callback
        2. Start listening
        3. Verify audio level updates are received
        4. Stop listening
        5. Verify audio level updates stop
        """
        # Create fresh instances
        mock_audio_engine = create_mock_audio_engine()
        voice_pipeline = VoicePipeline(audio_engine=mock_audio_engine)
        
        # Track audio levels with timestamps
        audio_level_events = []
        def track_audio_level(level):
            audio_level_events.append({
                "level": level,
                "state": voice_pipeline.get_state(session_id)
            })
        
        voice_pipeline.register_audio_level_callback(session_id, track_audio_level)
        
        # Initialize
        await voice_pipeline.initialize()
        
        # Verify no updates in IDLE state
        await asyncio.sleep(0.2)
        idle_updates = [e for e in audio_level_events if e["state"] == VoiceState.IDLE]
        assert len(idle_updates) == 0
        
        # Start listening
        await voice_pipeline.start_listening(session_id)
        
        # Wait for audio level updates
        await asyncio.sleep(0.3)
        
        # Verify updates during LISTENING state
        listening_updates = [e for e in audio_level_events if e["state"] == VoiceState.LISTENING]
        assert len(listening_updates) > 0
        
        # Stop listening
        await voice_pipeline.stop_listening(session_id)
        
        # Clear events
        audio_level_events.clear()
        
        # Wait and verify no more updates
        await asyncio.sleep(0.2)
        assert len(audio_level_events) == 0
    
    @pytest.mark.asyncio
    @given(session_id=session_ids())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_audio_level_callback_registration(self, session_id):
        """
        **Validates: Requirements 22.1**
        
        Property: Multiple callbacks can be registered for audio level updates,
        and all shall be notified.
        
        Test Strategy:
        1. Register multiple audio level callbacks
        2. Start listening
        3. Verify all callbacks receive updates
        """
        # Create fresh instances
        mock_audio_engine = create_mock_audio_engine()
        voice_pipeline = VoicePipeline(audio_engine=mock_audio_engine)
        
        # Register multiple callbacks
        callback1_levels = []
        callback2_levels = []
        callback3_levels = []
        
        voice_pipeline.register_audio_level_callback(session_id, lambda level: callback1_levels.append(level))
        voice_pipeline.register_audio_level_callback(session_id, lambda level: callback2_levels.append(level))
        voice_pipeline.register_audio_level_callback(session_id, lambda level: callback3_levels.append(level))
        
        # Initialize and start listening
        await voice_pipeline.initialize()
        await voice_pipeline.start_listening(session_id)
        
        # Wait for audio level updates
        await asyncio.sleep(0.3)
        
        # Stop listening
        await voice_pipeline.stop_listening(session_id)
        
        # Verify all callbacks received updates
        assert len(callback1_levels) > 0
        assert len(callback2_levels) > 0
        assert len(callback3_levels) > 0
        
        # Verify all callbacks received the same number of updates
        assert len(callback1_levels) == len(callback2_levels) == len(callback3_levels)
    
    @pytest.mark.asyncio
    @given(session_id=session_ids())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_audio_level_reset_on_state_change(self, session_id):
        """
        **Validates: Requirements 22.7**
        
        Property: When voice state changes from "listening" to any other state,
        the audio level shall reset to 0.
        
        Test Strategy:
        1. Start listening
        2. Wait for non-zero audio levels
        3. Stop listening
        4. Verify audio level is reset to 0
        """
        # Create fresh instances
        mock_audio_engine = create_mock_audio_engine()
        voice_pipeline = VoicePipeline(audio_engine=mock_audio_engine)
        
        # Track audio levels
        audio_levels = []
        def track_audio_level(level):
            audio_levels.append(level)
        
        voice_pipeline.register_audio_level_callback(session_id, track_audio_level)
        
        # Initialize and start listening
        await voice_pipeline.initialize()
        await voice_pipeline.start_listening(session_id)
        
        # Wait for audio level updates
        await asyncio.sleep(0.3)
        
        # Verify we received some non-zero levels during listening
        # (In the mock implementation, levels are random between 0.1 and 0.8)
        assert len(audio_levels) > 0
        
        # Stop listening
        await voice_pipeline.stop_listening(session_id)
        
        # Verify audio level is reset to 0
        final_level = voice_pipeline.get_audio_level()
        assert final_level == 0.0
        
        # Verify the last callback received was 0
        assert audio_levels[-1] == 0.0
    
    @pytest.mark.asyncio
    @given(session_id=session_ids())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_audio_level_update_frequency(self, session_id):
        """
        **Validates: Requirements 22.1**
        
        Property: Audio level updates shall be sent approximately every 100ms
        during listening state.
        
        Test Strategy:
        1. Start listening
        2. Wait for 500ms
        3. Verify approximately 5 updates were received (500ms / 100ms)
        """
        # Create fresh instances
        mock_audio_engine = create_mock_audio_engine()
        voice_pipeline = VoicePipeline(audio_engine=mock_audio_engine)
        
        # Track audio levels
        audio_levels = []
        def track_audio_level(level):
            audio_levels.append(level)
        
        voice_pipeline.register_audio_level_callback(session_id, track_audio_level)
        
        # Initialize and start listening
        await voice_pipeline.initialize()
        await voice_pipeline.start_listening(session_id)
        
        # Wait for 500ms
        await asyncio.sleep(0.5)
        
        # Stop listening
        await voice_pipeline.stop_listening(session_id)
        
        # Verify approximately 5 updates were received (allow ±2 for timing variance)
        # Expected: 500ms / 100ms = 5 updates
        assert 3 <= len(audio_levels) <= 7, f"Expected ~5 updates, got {len(audio_levels)}"
    
    @pytest.mark.asyncio
    @given(session_id=session_ids())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_audio_level_session_isolation(self, session_id):
        """
        **Validates: Requirements 2.4 (Session State Isolation)**
        
        Property: Audio level updates for different sessions shall be independent.
        
        Test Strategy:
        1. Create two sessions
        2. Start listening for both
        3. Verify each session receives its own audio level updates
        4. Verify callbacks are session-specific
        """
        # Create fresh instances
        mock_audio_engine = create_mock_audio_engine()
        voice_pipeline = VoicePipeline(audio_engine=mock_audio_engine)
        
        # Create second session
        session_id_2 = session_id + "_2"
        
        # Track audio levels per session
        session1_levels = []
        session2_levels = []
        
        voice_pipeline.register_audio_level_callback(session_id, lambda level: session1_levels.append(level))
        voice_pipeline.register_audio_level_callback(session_id_2, lambda level: session2_levels.append(level))
        
        # Initialize
        await voice_pipeline.initialize()
        
        # Start listening for session 1 only
        await voice_pipeline.start_listening(session_id)
        
        # Wait for updates
        await asyncio.sleep(0.3)
        
        # Stop listening for session 1
        await voice_pipeline.stop_listening(session_id)
        
        # Verify session 1 received updates
        assert len(session1_levels) > 0
        
        # Verify session 2 did not receive updates (it wasn't listening)
        assert len(session2_levels) == 0
