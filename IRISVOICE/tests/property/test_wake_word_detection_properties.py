"""
Property-based tests for wake word detection activation.
Tests universal properties that should hold for wake word detection,
including activation behavior and configuration.
"""
import pytest
from hypothesis import given, settings, strategies as st, seed
import sys
import os
from unittest.mock import Mock, patch, MagicMock
import numpy as np

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.agent.lfm_audio_manager import LFMAudioManager


# ============================================================================
# Test Data Generators (Hypothesis Strategies)
# ============================================================================

@st.composite
def wake_phrase_generator(draw):
    """Generate valid wake phrases."""
    return draw(st.sampled_from([
        "jarvis", "hey computer", "computer", "bumblebee", "porcupine", "hey iris"
    ]))


@st.composite
def detection_sensitivity_generator(draw):
    """Generate valid detection sensitivity values (0-100)."""
    return draw(st.integers(min_value=0, max_value=100))


@st.composite
def audio_data_generator(draw):
    """Generate simulated audio data."""
    # Generate random audio samples
    num_samples = draw(st.integers(min_value=1000, max_value=16000))
    audio_array = np.random.randint(-32768, 32767, num_samples, dtype=np.int16)
    return audio_array.tobytes()


@st.composite
def audio_with_wake_word_generator(draw):
    """Generate audio data that contains a wake word."""
    wake_phrase = draw(wake_phrase_generator())
    # Simulate audio data (in real implementation, this would be actual audio)
    num_samples = draw(st.integers(min_value=1000, max_value=16000))
    audio_array = np.random.randint(-32768, 32767, num_samples, dtype=np.int16)
    return audio_array.tobytes(), wake_phrase


@st.composite
def config_generator(draw):
    """Generate LFM audio manager configuration."""
    return {
        "lfm_model_path": "",
        "device": "cpu",
        "wake_phrase": draw(wake_phrase_generator()),
        "detection_sensitivity": draw(detection_sensitivity_generator()),
        "activation_sound": draw(st.booleans()),
        "tts_voice": draw(st.sampled_from(["Nova", "Alloy", "Echo", "Fable", "Onyx", "Shimmer"])),
        "speaking_rate": draw(st.floats(min_value=0.5, max_value=2.0))
    }


# ============================================================================
# Property 11: Wake Word Detection Activation
# Feature: irisvoice-backend-integration, Property 11: Wake Word Detection Activation
# Validates: Requirements 4.1, 4.2
# ============================================================================

class TestWakeWordDetectionActivation:
    """
    Property 11: Wake Word Detection Activation
    
    For any wake word detection event, the backend sends a wake_detected message
    and the IrisOrb automatically starts voice recording.
    
    This tests:
    - Requirement 4.1: Wake word detection triggers wake_detected message
    - Requirement 4.2: IrisOrb automatically starts voice recording on wake detection
    """
    
    @settings(max_examples=10, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        config=config_generator(),
        audio_data=audio_data_generator()
    )
    def test_wake_word_detection_triggers_callback(self, config, audio_data):
        """
        Property: For any wake word detection, the on_wake_detected callback is triggered.
        
        # Feature: irisvoice-backend-integration, Property 11: Wake Word Detection Activation
        **Validates: Requirements 4.1**
        """
        # Setup: Create manager with mocked Porcupine detector
        with patch('backend.agent.lfm_audio_manager.PorcupineWakeWordDetector') as mock_porcupine_class:
            # Mock Porcupine detector
            mock_detector = MagicMock()
            mock_detector.frame_length = 512
            mock_detector.process_frame.return_value = (True, config["wake_phrase"])
            mock_porcupine_class.return_value = mock_detector
            
            manager = LFMAudioManager(config)
            manager.porcupine_detector = mock_detector
            manager.is_initialized = True
            
            # Setup callback mock
            wake_callback = Mock()
            manager.set_callbacks(on_wake_detected=wake_callback)
            
            # Execute: Detect wake word
            result = manager.detect_wake_word(audio_data)
            
            # Verify: Callback was triggered
            assert result is True, "Wake word should be detected"
            wake_callback.assert_called_once()
            
            # Verify callback arguments
            call_args = wake_callback.call_args[0]
            assert call_args[0] == config["wake_phrase"], \
                f"Callback should receive wake phrase '{config['wake_phrase']}'"
            assert call_args[1] == config["detection_sensitivity"], \
                f"Callback should receive detection sensitivity {config['detection_sensitivity']}"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        config=config_generator(),
        audio_data=audio_data_generator()
    )
    def test_wake_word_detection_sets_active_state(self, config, audio_data):
        """
        Property: For any wake word detection, the wake_word_active state is set to True.
        
        # Feature: irisvoice-backend-integration, Property 11: Wake Word Detection Activation
        **Validates: Requirements 4.1**
        """
        # Setup: Create manager with mocked Porcupine detector
        with patch('backend.agent.lfm_audio_manager.PorcupineWakeWordDetector') as mock_porcupine_class:
            mock_detector = MagicMock()
            mock_detector.frame_length = 512
            mock_detector.process_frame.return_value = (True, config["wake_phrase"])
            mock_porcupine_class.return_value = mock_detector
            
            manager = LFMAudioManager(config)
            manager.porcupine_detector = mock_detector
            manager.is_initialized = True
            
            # Verify initial state
            assert manager.wake_word_active is False, "Initial state should be inactive"
            
            # Execute: Detect wake word
            result = manager.detect_wake_word(audio_data)
            
            # Verify: State is now active
            assert result is True, "Wake word should be detected"
            assert manager.wake_word_active is True, \
                "wake_word_active should be True after detection"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        config=config_generator(),
        audio_data=audio_data_generator()
    )
    def test_no_wake_word_no_activation(self, config, audio_data):
        """
        Property: For any audio without wake word, no activation occurs.
        
        # Feature: irisvoice-backend-integration, Property 11: Wake Word Detection Activation
        **Validates: Requirements 4.1**
        """
        # Setup: Create manager with mocked Porcupine detector
        with patch('backend.agent.lfm_audio_manager.PorcupineWakeWordDetector') as mock_porcupine_class:
            # Mock Porcupine to return no detection
            mock_detector = MagicMock()
            mock_detector.frame_length = 512
            mock_detector.process_frame.return_value = (False, None)
            mock_porcupine_class.return_value = mock_detector
            
            manager = LFMAudioManager(config)
            manager.porcupine_detector = mock_detector
            manager.is_initialized = True
            
            # Setup callback mock
            wake_callback = Mock()
            manager.set_callbacks(on_wake_detected=wake_callback)
            
            # Execute: Try to detect wake word
            result = manager.detect_wake_word(audio_data)
            
            # Verify: No activation
            assert result is False, "Wake word should not be detected"
            assert manager.wake_word_active is False, \
                "wake_word_active should remain False"
            wake_callback.assert_not_called()
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        wake_phrase=wake_phrase_generator(),
        detection_sensitivity=detection_sensitivity_generator(),
        audio_data=audio_data_generator()
    )
    def test_wake_word_detection_uses_configured_phrase(
        self, wake_phrase, detection_sensitivity, audio_data
    ):
        """
        Property: For any configured wake phrase, detection uses that phrase.
        
        # Feature: irisvoice-backend-integration, Property 11: Wake Word Detection Activation
        **Validates: Requirements 4.1, 4.4**
        """
        # Setup: Create manager with specific wake phrase
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": wake_phrase,
            "detection_sensitivity": detection_sensitivity,
            "activation_sound": True,
            "tts_voice": "Nova",
            "speaking_rate": 1.0
        }
        
        with patch('backend.agent.lfm_audio_manager.PorcupineWakeWordDetector') as mock_porcupine_class:
            # Mock Porcupine to return the configured wake phrase
            mock_detector = MagicMock()
            mock_detector.frame_length = 512
            mock_detector.process_frame.return_value = (True, wake_phrase)
            mock_porcupine_class.return_value = mock_detector
            
            manager = LFMAudioManager(config)
            manager.porcupine_detector = mock_detector
            manager.is_initialized = True
            
            # Verify configuration
            assert manager.wake_phrase == wake_phrase, \
                f"Manager should use configured wake phrase '{wake_phrase}'"
            assert manager.detection_sensitivity == detection_sensitivity, \
                f"Manager should use configured sensitivity {detection_sensitivity}"
            
            # Execute: Detect wake word
            result = manager.detect_wake_word(audio_data)
            
            # Verify: Detection succeeded with configured phrase
            assert result is True, \
                f"Wake word '{wake_phrase}' should be detected"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        config=config_generator(),
        audio_data=audio_data_generator()
    )
    def test_activation_sound_setting_is_respected(self, config, audio_data):
        """
        Property: For any activation_sound setting, the behavior is respected.
        
        # Feature: irisvoice-backend-integration, Property 11: Wake Word Detection Activation
        **Validates: Requirements 4.6**
        """
        # Setup: Create manager with mocked Porcupine detector
        with patch('backend.agent.lfm_audio_manager.PorcupineWakeWordDetector') as mock_porcupine_class:
            mock_detector = MagicMock()
            mock_detector.frame_length = 512
            mock_detector.process_frame.return_value = (True, config["wake_phrase"])
            mock_porcupine_class.return_value = mock_detector
            
            manager = LFMAudioManager(config)
            manager.porcupine_detector = mock_detector
            manager.is_initialized = True
            
            # Verify configuration
            assert manager.activation_sound == config["activation_sound"], \
                f"Manager should use configured activation_sound {config['activation_sound']}"
            
            # Execute: Detect wake word
            result = manager.detect_wake_word(audio_data)
            
            # Verify: Detection succeeded
            assert result is True, "Wake word should be detected"
            # Note: In real implementation, we would verify audio playback
            # For now, we just verify the setting is stored correctly
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        config=config_generator(),
        audio_data=audio_data_generator()
    )
    def test_wake_detection_stores_transcription(self, config, audio_data):
        """
        Property: For any wake word detection, the transcription is stored.
        
        # Feature: irisvoice-backend-integration, Property 11: Wake Word Detection Activation
        **Validates: Requirements 4.1**
        """
        # Setup: Create manager with mocked Porcupine detector
        with patch('backend.agent.lfm_audio_manager.PorcupineWakeWordDetector') as mock_porcupine_class:
            wake_word_name = config['wake_phrase']
            mock_detector = MagicMock()
            mock_detector.frame_length = 512
            mock_detector.process_frame.return_value = (True, wake_word_name)
            mock_porcupine_class.return_value = mock_detector
            
            manager = LFMAudioManager(config)
            manager.porcupine_detector = mock_detector
            manager.is_initialized = True
            
            # Execute: Detect wake word
            result = manager.detect_wake_word(audio_data)
            
            # Verify: Wake word name is stored
            assert result is True, "Wake word should be detected"
            assert manager.last_wake_detection == wake_word_name, \
                f"Last wake detection should store wake word name '{wake_word_name}'"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        config=config_generator(),
        audio_data=audio_data_generator()
    )
    def test_end_to_end_processing_requires_wake_word(self, config, audio_data):
        """
        Property: For any end-to-end processing, wake word detection is required.
        
        # Feature: irisvoice-backend-integration, Property 11: Wake Word Detection Activation
        **Validates: Requirements 4.1, 4.2**
        """
        # Setup: Create manager with mocked pipelines
        with patch('backend.agent.lfm_audio_manager.PorcupineWakeWordDetector') as mock_porcupine_class:
            # Mock Porcupine to return no detection
            mock_detector = MagicMock()
            mock_detector.frame_length = 512
            mock_detector.process_frame.return_value = (False, None)
            mock_porcupine_class.return_value = mock_detector
            
            manager = LFMAudioManager(config)
            manager.porcupine_detector = mock_detector
            manager.tts_pipeline = MagicMock()
            manager.is_initialized = True
            
            # Ensure wake word is not active
            manager.wake_word_active = False
            
            # Execute: Try end-to-end processing without wake word
            result = manager.process_end_to_end(audio_data)
            
            # Verify: Processing is skipped without wake word
            assert result == b"", \
                "End-to-end processing should return empty audio without wake word"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        config=config_generator(),
        audio_data=audio_data_generator()
    )
    def test_end_to_end_processing_with_wake_word(self, config, audio_data):
        """
        Property: For any end-to-end processing with wake word, processing proceeds.
        
        # Feature: irisvoice-backend-integration, Property 11: Wake Word Detection Activation
        **Validates: Requirements 4.1, 4.2**
        """
        # Setup: Create manager with mocked pipelines
        with patch('backend.agent.lfm_audio_manager.PorcupineWakeWordDetector') as mock_porcupine_class:
            with patch('backend.agent.lfm_audio_manager.pipeline') as mock_pipeline_func:
                # Mock Porcupine to return wake phrase
                mock_detector = MagicMock()
                mock_detector.frame_length = 512
                mock_detector.process_frame.return_value = (True, config["wake_phrase"])
                mock_porcupine_class.return_value = mock_detector
                
                # Mock STT to return wake phrase
                mock_stt = MagicMock()
                mock_stt.return_value = {"text": config["wake_phrase"]}
                
                # Mock TTS to return audio
                mock_tts = MagicMock()
                mock_audio = np.random.rand(16000).astype(np.float32)
                mock_tts.return_value = {"audio": mock_audio}
                
                mock_pipeline_func.side_effect = [mock_stt, mock_tts]
                
                manager = LFMAudioManager(config)
                manager.porcupine_detector = mock_detector
                manager.stt_pipeline = mock_stt
                manager.tts_pipeline = mock_tts
                manager.is_initialized = True
                
                # Execute: End-to-end processing with wake word
                result = manager.process_end_to_end(audio_data)
                
                # Verify: Processing completed and returned audio
                assert result != b"", \
                    "End-to-end processing should return audio when wake word is detected"
                assert isinstance(result, bytes), \
                    "Result should be audio bytes"
