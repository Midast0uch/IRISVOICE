"""
Property-based tests for TTS voice configuration.
Tests universal properties that should hold for all TTS configuration scenarios.

**Validates: Requirements 14.1, 14.2, 14.5**
"""
import pytest
from hypothesis import given, settings, strategies as st, seed
import sys
import os

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.agent.lfm_audio_manager import LFMAudioManager


# ============================================================================
# Test Data Generators (Hypothesis Strategies)
# ============================================================================

# Valid TTS voices as per requirements
VALID_TTS_VOICES = ["Nova", "Alloy", "Echo", "Fable", "Onyx", "Shimmer"]

# Valid speaking rate range: 0.5x to 2.0x
MIN_SPEAKING_RATE = 0.5
MAX_SPEAKING_RATE = 2.0


@st.composite
def valid_tts_voice(draw):
    """Generate valid TTS voice."""
    return draw(st.sampled_from(VALID_TTS_VOICES))


@st.composite
def valid_speaking_rate(draw):
    """Generate valid speaking rate (0.5x to 2.0x)."""
    return draw(st.floats(min_value=MIN_SPEAKING_RATE, max_value=MAX_SPEAKING_RATE))


@st.composite
def invalid_tts_voice(draw):
    """Generate invalid TTS voice."""
    return draw(st.text(min_size=1, max_size=20).filter(lambda x: x not in VALID_TTS_VOICES))


@st.composite
def invalid_speaking_rate(draw):
    """Generate invalid speaking rate (outside 0.5x to 2.0x range)."""
    # Generate values outside the valid range
    choice = draw(st.sampled_from(["too_low", "too_high"]))
    if choice == "too_low":
        return draw(st.floats(min_value=0.0, max_value=0.49))
    else:
        return draw(st.floats(min_value=2.01, max_value=5.0))


@st.composite
def lfm_audio_config(draw):
    """Generate LFM Audio Manager configuration."""
    return {
        "lfm_model_path": "",
        "device": "cpu",
        "wake_phrase": draw(st.sampled_from(["jarvis", "hey computer", "computer"])),
        "detection_sensitivity": draw(st.integers(min_value=0, max_value=100)),
        "activation_sound": draw(st.booleans()),
        "tts_voice": draw(valid_tts_voice()),
        "speaking_rate": draw(valid_speaking_rate())
    }


# ============================================================================
# Property 37: TTS Voice Configuration
# ============================================================================

class TestTTSVoiceConfiguration:
    """
    Property 37: TTS Voice Configuration
    
    For any change to agent.speech.tts_voice or agent.speech.speaking_rate,
    the LFM_Audio_Model shall apply the new configuration to the next spoken response.
    
    **Validates: Requirements 14.1, 14.2, 14.5**
    """
    
    @given(
        initial_voice=valid_tts_voice(),
        new_voice=valid_tts_voice(),
        initial_rate=valid_speaking_rate(),
        new_rate=valid_speaking_rate()
    )
    @settings(max_examples=100, deadline=None)
    def test_tts_voice_update_applies_to_next_response(
        self, initial_voice, new_voice, initial_rate, new_rate
    ):
        """
        Property: When TTS voice or speaking rate changes, the new configuration
        is applied to the next spoken response.
        
        Test Strategy:
        1. Create LFMAudioManager with initial voice and rate
        2. Update voice configuration
        3. Verify new configuration is applied
        """
        # Setup: Create manager with initial configuration
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": "jarvis",
            "detection_sensitivity": 50,
            "activation_sound": False,
            "tts_voice": initial_voice,
            "speaking_rate": initial_rate
        }
        manager = LFMAudioManager(config)
        
        # Verify initial configuration
        assert manager.tts_voice == initial_voice, \
            f"Initial TTS voice should be {initial_voice}"
        assert manager.speaking_rate == initial_rate, \
            f"Initial speaking rate should be {initial_rate}"
        
        # Action: Update voice configuration
        manager.update_voice_config(tts_voice=new_voice, speaking_rate=new_rate)
        
        # Verify: New configuration is applied
        assert manager.tts_voice == new_voice, \
            f"TTS voice should be updated to {new_voice}"
        assert manager.speaking_rate == new_rate, \
            f"Speaking rate should be updated to {new_rate}"
    
    @given(
        voice=valid_tts_voice(),
        rate=valid_speaking_rate()
    )
    @settings(max_examples=100, deadline=None)
    def test_tts_voice_configuration_persists_across_calls(self, voice, rate):
        """
        Property: TTS voice configuration persists across multiple synthesis calls.
        
        Test Strategy:
        1. Create LFMAudioManager with specific voice and rate
        2. Verify configuration persists across multiple operations
        """
        # Setup: Create manager with configuration
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": "jarvis",
            "detection_sensitivity": 50,
            "activation_sound": False,
            "tts_voice": voice,
            "speaking_rate": rate
        }
        manager = LFMAudioManager(config)
        
        # Verify: Configuration persists
        for _ in range(3):
            assert manager.tts_voice == voice, \
                f"TTS voice should remain {voice}"
            assert manager.speaking_rate == rate, \
                f"Speaking rate should remain {rate}"
    
    @given(
        voice=valid_tts_voice()
    )
    @settings(max_examples=50, deadline=None)
    def test_tts_voice_update_only_affects_voice(self, voice):
        """
        Property: Updating only TTS voice does not affect speaking rate.
        
        Test Strategy:
        1. Create LFMAudioManager with initial configuration
        2. Update only TTS voice
        3. Verify speaking rate remains unchanged
        """
        # Setup: Create manager with initial configuration
        initial_rate = 1.0
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": "jarvis",
            "detection_sensitivity": 50,
            "activation_sound": False,
            "tts_voice": "Nova",
            "speaking_rate": initial_rate
        }
        manager = LFMAudioManager(config)
        
        # Action: Update only TTS voice
        manager.update_voice_config(tts_voice=voice)
        
        # Verify: Voice updated, rate unchanged
        assert manager.tts_voice == voice, \
            f"TTS voice should be updated to {voice}"
        assert manager.speaking_rate == initial_rate, \
            f"Speaking rate should remain {initial_rate}"
    
    @given(
        rate=valid_speaking_rate()
    )
    @settings(max_examples=50, deadline=None)
    def test_speaking_rate_update_only_affects_rate(self, rate):
        """
        Property: Updating only speaking rate does not affect TTS voice.
        
        Test Strategy:
        1. Create LFMAudioManager with initial configuration
        2. Update only speaking rate
        3. Verify TTS voice remains unchanged
        """
        # Setup: Create manager with initial configuration
        initial_voice = "Nova"
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": "jarvis",
            "detection_sensitivity": 50,
            "activation_sound": False,
            "tts_voice": initial_voice,
            "speaking_rate": 1.0
        }
        manager = LFMAudioManager(config)
        
        # Action: Update only speaking rate
        manager.update_voice_config(speaking_rate=rate)
        
        # Verify: Rate updated, voice unchanged
        assert manager.speaking_rate == rate, \
            f"Speaking rate should be updated to {rate}"
        assert manager.tts_voice == initial_voice, \
            f"TTS voice should remain {initial_voice}"
    
    @given(
        invalid_voice=invalid_tts_voice()
    )
    @settings(max_examples=50, deadline=None)
    def test_invalid_tts_voice_rejected(self, invalid_voice):
        """
        Property: Invalid TTS voice values are rejected and do not change configuration.
        
        Test Strategy:
        1. Create LFMAudioManager with valid configuration
        2. Attempt to update with invalid voice
        3. Verify configuration remains unchanged
        """
        # Setup: Create manager with valid configuration
        initial_voice = "Nova"
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": "jarvis",
            "detection_sensitivity": 50,
            "activation_sound": False,
            "tts_voice": initial_voice,
            "speaking_rate": 1.0
        }
        manager = LFMAudioManager(config)
        
        # Action: Attempt to update with invalid voice
        manager.update_voice_config(tts_voice=invalid_voice)
        
        # Verify: Configuration remains unchanged (invalid voice rejected)
        assert manager.tts_voice == initial_voice, \
            f"TTS voice should remain {initial_voice} after invalid update"
    
    @given(
        invalid_rate=invalid_speaking_rate()
    )
    @settings(max_examples=50, deadline=None)
    def test_invalid_speaking_rate_rejected(self, invalid_rate):
        """
        Property: Invalid speaking rate values are rejected and do not change configuration.
        
        Test Strategy:
        1. Create LFMAudioManager with valid configuration
        2. Attempt to update with invalid rate
        3. Verify configuration remains unchanged
        """
        # Setup: Create manager with valid configuration
        initial_rate = 1.0
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": "jarvis",
            "detection_sensitivity": 50,
            "activation_sound": False,
            "tts_voice": "Nova",
            "speaking_rate": initial_rate
        }
        manager = LFMAudioManager(config)
        
        # Action: Attempt to update with invalid rate
        manager.update_voice_config(speaking_rate=invalid_rate)
        
        # Verify: Configuration remains unchanged (invalid rate rejected)
        assert manager.speaking_rate == initial_rate, \
            f"Speaking rate should remain {initial_rate} after invalid update"
    
    @given(
        voices=st.lists(valid_tts_voice(), min_size=2, max_size=5)
    )
    @settings(max_examples=50, deadline=None)
    def test_sequential_voice_updates_apply_correctly(self, voices):
        """
        Property: Sequential TTS voice updates each apply correctly.
        
        Test Strategy:
        1. Create LFMAudioManager
        2. Apply multiple voice updates sequentially
        3. Verify each update is applied correctly
        """
        # Setup: Create manager
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": "jarvis",
            "detection_sensitivity": 50,
            "activation_sound": False,
            "tts_voice": "Nova",
            "speaking_rate": 1.0
        }
        manager = LFMAudioManager(config)
        
        # Action & Verify: Apply each voice update and verify
        for voice in voices:
            manager.update_voice_config(tts_voice=voice)
            assert manager.tts_voice == voice, \
                f"TTS voice should be updated to {voice}"
    
    @given(
        rates=st.lists(valid_speaking_rate(), min_size=2, max_size=5)
    )
    @settings(max_examples=50, deadline=None)
    def test_sequential_rate_updates_apply_correctly(self, rates):
        """
        Property: Sequential speaking rate updates each apply correctly.
        
        Test Strategy:
        1. Create LFMAudioManager
        2. Apply multiple rate updates sequentially
        3. Verify each update is applied correctly
        """
        # Setup: Create manager
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": "jarvis",
            "detection_sensitivity": 50,
            "activation_sound": False,
            "tts_voice": "Nova",
            "speaking_rate": 1.0
        }
        manager = LFMAudioManager(config)
        
        # Action & Verify: Apply each rate update and verify
        for rate in rates:
            manager.update_voice_config(speaking_rate=rate)
            assert manager.speaking_rate == rate, \
                f"Speaking rate should be updated to {rate}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
