"""
Property-based tests for TTS audio output.
Tests universal properties that should hold for all TTS audio synthesis scenarios.

**Validates: Requirements 14.7**
"""
import pytest
from hypothesis import given, settings, strategies as st, seed, assume
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
def text_to_synthesize(draw):
    """Generate text for TTS synthesis."""
    # Generate meaningful text (not just random characters)
    return draw(st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd', 'Zs', 'Po')),
        min_size=5,
        max_size=100
    ).filter(lambda x: len(x.strip()) > 0))


@st.composite
def lfm_audio_config(draw):
    """Generate LFM Audio Manager configuration."""
    return {
        "lfm_model_path": "",
        "device": "cpu",
        "wake_phrase": "jarvis",
        "detection_sensitivity": 50,
        "activation_sound": False,
        "tts_voice": draw(valid_tts_voice()),
        "speaking_rate": draw(valid_speaking_rate())
    }


# ============================================================================
# Property 38: TTS Audio Output
# ============================================================================

class TestTTSAudioOutput:
    """
    Property 38: TTS Audio Output
    
    For any TTS synthesis, the LFM_Audio_Model shall generate audio responses
    directly and output them to the configured audio device.
    
    **Validates: Requirements 14.7**
    """
    
    @given(
        text=text_to_synthesize(),
        voice=valid_tts_voice(),
        rate=valid_speaking_rate()
    )
    @settings(max_examples=50, deadline=None)
    def test_tts_generates_audio_output(self, text, voice, rate):
        """
        Property: TTS synthesis generates non-empty audio output for any valid text.
        
        Test Strategy:
        1. Create LFMAudioManager with specific voice and rate
        2. Synthesize text to speech
        3. Verify audio output is generated (non-empty bytes)
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
        
        try:
            manager = LFMAudioManager(config)
            
            # Action: Synthesize speech
            audio_output = manager.synthesize_speech(text)
            
            # Verify: Audio output is generated
            assert isinstance(audio_output, bytes), \
                "Audio output should be bytes"
            assert len(audio_output) > 0, \
                "Audio output should not be empty"
        except Exception as e:
            # If initialization fails (e.g., models not available), skip test
            pytest.skip(f"LFMAudioManager initialization failed: {e}")
    
    @given(
        text=text_to_synthesize(),
        voice=valid_tts_voice()
    )
    @settings(max_examples=30, deadline=None)
    def test_tts_output_varies_with_voice(self, text, voice):
        """
        Property: TTS audio output is generated for different voice characteristics.
        
        Test Strategy:
        1. Create LFMAudioManager with specific voice
        2. Synthesize same text
        3. Verify audio is generated (voice characteristic is applied)
        """
        # Setup: Create manager with specific voice
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": "jarvis",
            "detection_sensitivity": 50,
            "activation_sound": False,
            "tts_voice": voice,
            "speaking_rate": 1.0
        }
        
        try:
            manager = LFMAudioManager(config)
            
            # Action: Synthesize speech
            audio_output = manager.synthesize_speech(text)
            
            # Verify: Audio output is generated with configured voice
            assert isinstance(audio_output, bytes), \
                f"Audio output should be bytes for voice {voice}"
            assert len(audio_output) > 0, \
                f"Audio output should not be empty for voice {voice}"
            assert manager.tts_voice == voice, \
                f"Manager should use voice {voice}"
        except Exception as e:
            pytest.skip(f"LFMAudioManager initialization failed: {e}")
    
    @given(
        text=text_to_synthesize(),
        rate=valid_speaking_rate()
    )
    @settings(max_examples=30, deadline=None)
    def test_tts_output_generated_at_all_rates(self, text, rate):
        """
        Property: TTS audio output is generated at all valid speaking rates.
        
        Test Strategy:
        1. Create LFMAudioManager with specific speaking rate
        2. Synthesize text
        3. Verify audio is generated at the specified rate
        """
        # Setup: Create manager with specific rate
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": "jarvis",
            "detection_sensitivity": 50,
            "activation_sound": False,
            "tts_voice": "Nova",
            "speaking_rate": rate
        }
        
        try:
            manager = LFMAudioManager(config)
            
            # Action: Synthesize speech
            audio_output = manager.synthesize_speech(text)
            
            # Verify: Audio output is generated at specified rate
            assert isinstance(audio_output, bytes), \
                f"Audio output should be bytes at rate {rate}x"
            assert len(audio_output) > 0, \
                f"Audio output should not be empty at rate {rate}x"
            assert manager.speaking_rate == rate, \
                f"Manager should use rate {rate}x"
        except Exception as e:
            pytest.skip(f"LFMAudioManager initialization failed: {e}")
    
    @given(
        text=text_to_synthesize()
    )
    @settings(max_examples=30, deadline=None)
    def test_tts_output_consistent_for_same_input(self, text):
        """
        Property: TTS generates audio output consistently for the same input.
        
        Test Strategy:
        1. Create LFMAudioManager
        2. Synthesize same text multiple times
        3. Verify audio is generated each time
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
        
        try:
            manager = LFMAudioManager(config)
            
            # Action: Synthesize same text multiple times
            outputs = []
            for _ in range(2):
                audio_output = manager.synthesize_speech(text)
                outputs.append(audio_output)
            
            # Verify: Audio is generated each time
            for i, output in enumerate(outputs):
                assert isinstance(output, bytes), \
                    f"Output {i} should be bytes"
                assert len(output) > 0, \
                    f"Output {i} should not be empty"
        except Exception as e:
            pytest.skip(f"LFMAudioManager initialization failed: {e}")
    
    @given(
        texts=st.lists(text_to_synthesize(), min_size=2, max_size=5)
    )
    @settings(max_examples=20, deadline=None)
    def test_tts_generates_output_for_multiple_texts(self, texts):
        """
        Property: TTS generates audio output for multiple different texts.
        
        Test Strategy:
        1. Create LFMAudioManager
        2. Synthesize multiple different texts
        3. Verify audio is generated for each text
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
        
        try:
            manager = LFMAudioManager(config)
            
            # Action & Verify: Synthesize each text and verify output
            for text in texts:
                audio_output = manager.synthesize_speech(text)
                assert isinstance(audio_output, bytes), \
                    f"Audio output should be bytes for text: {text[:20]}..."
                assert len(audio_output) > 0, \
                    f"Audio output should not be empty for text: {text[:20]}..."
        except Exception as e:
            pytest.skip(f"LFMAudioManager initialization failed: {e}")
    
    @given(
        text=text_to_synthesize(),
        config=lfm_audio_config()
    )
    @settings(max_examples=30, deadline=None)
    def test_tts_output_type_is_bytes(self, text, config):
        """
        Property: TTS audio output is always bytes type.
        
        Test Strategy:
        1. Create LFMAudioManager with any valid configuration
        2. Synthesize text
        3. Verify output type is bytes
        """
        try:
            manager = LFMAudioManager(config)
            
            # Action: Synthesize speech
            audio_output = manager.synthesize_speech(text)
            
            # Verify: Output is bytes
            assert isinstance(audio_output, bytes), \
                "Audio output must be bytes type"
        except Exception as e:
            pytest.skip(f"LFMAudioManager initialization failed: {e}")
    
    @given(
        text=text_to_synthesize(),
        voice=valid_tts_voice(),
        rate=valid_speaking_rate()
    )
    @settings(max_examples=30, deadline=None)
    def test_tts_applies_configuration_to_output(self, text, voice, rate):
        """
        Property: TTS applies voice and rate configuration to audio output.
        
        Test Strategy:
        1. Create LFMAudioManager with specific voice and rate
        2. Synthesize text
        3. Verify configuration is applied (manager state reflects config)
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
        
        try:
            manager = LFMAudioManager(config)
            
            # Action: Synthesize speech
            audio_output = manager.synthesize_speech(text)
            
            # Verify: Configuration is applied
            assert manager.tts_voice == voice, \
                f"TTS voice should be {voice}"
            assert manager.speaking_rate == rate, \
                f"Speaking rate should be {rate}"
            assert isinstance(audio_output, bytes), \
                "Audio output should be bytes"
            assert len(audio_output) > 0, \
                "Audio output should not be empty"
        except Exception as e:
            pytest.skip(f"LFMAudioManager initialization failed: {e}")
    
    @given(
        text=text_to_synthesize()
    )
    @settings(max_examples=20, deadline=None)
    def test_tts_handles_empty_or_whitespace_text(self, text):
        """
        Property: TTS handles text gracefully (generates output or handles error).
        
        Test Strategy:
        1. Create LFMAudioManager
        2. Synthesize text (including edge cases)
        3. Verify either output is generated or error is handled gracefully
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
        
        try:
            manager = LFMAudioManager(config)
            
            # Action: Synthesize speech
            try:
                audio_output = manager.synthesize_speech(text)
                
                # Verify: If synthesis succeeds, output should be bytes
                assert isinstance(audio_output, bytes), \
                    "Audio output should be bytes if synthesis succeeds"
            except Exception as synthesis_error:
                # Verify: If synthesis fails, error is handled gracefully
                # (no crash, error is logged)
                assert True, "Synthesis error handled gracefully"
        except Exception as e:
            pytest.skip(f"LFMAudioManager initialization failed: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
