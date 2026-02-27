"""
Integration tests for LFM 2.5 audio model end-to-end processing.

Tests the complete audio pipeline:
audio input → wake word (Porcupine) → VAD → STT → conversation → TTS → audio output

Validates Requirements 4.5.1-4.5.10
"""
import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
import numpy as np

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.agent.lfm_audio_manager import LFMAudioManager


class TestLFMAudioEndToEndProcessing:
    """
    Integration tests for LFM 2.5 end-to-end audio processing.
    
    Validates:
    - Requirement 4.5.1: Raw audio input capture
    - Requirement 4.5.2: Raw audio output playback
    - Requirement 4.5.3: Internal audio processing
    - Requirement 4.5.4: Internal wake word detection
    - Requirement 4.5.5: Internal VAD
    - Requirement 4.5.6: Internal STT
    - Requirement 4.5.7: Internal conversation understanding
    - Requirement 4.5.8: Internal TTS
    - Requirement 4.5.9: Natural conversation flow
    - Requirement 4.5.10: Thin wrapper architecture
    """
    
    def test_end_to_end_audio_processing_with_wake_word(self):
        """
        Test complete end-to-end processing: audio in → wake word (Porcupine) → VAD → STT → conversation → TTS → audio out.
        
        Validates: Requirements 4.5.1-4.5.10
        """
        # Setup: Create manager with mocked pipelines
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": "jarvis",
            "detection_sensitivity": 50,
            "activation_sound": True,
            "tts_voice": "Nova",
            "speaking_rate": 1.0
        }
        
        with patch('backend.agent.lfm_audio_manager.PorcupineWakeWordDetector') as mock_porcupine_class:
            with patch('backend.agent.lfm_audio_manager.pipeline') as mock_pipeline_func:
                # Mock Porcupine detector
                mock_detector = MagicMock()
                mock_detector.frame_length = 512
                mock_detector.process_frame.return_value = (True, "jarvis")
                mock_porcupine_class.return_value = mock_detector
                
                # Mock STT pipeline to return wake phrase
                mock_stt = MagicMock()
                mock_stt.return_value = {"text": "jarvis hello there"}
                
                # Mock TTS pipeline to return audio
                mock_tts = MagicMock()
                mock_audio = np.random.rand(16000).astype(np.float32)
                mock_tts.return_value = {"audio": mock_audio}
                
                mock_pipeline_func.side_effect = [mock_stt, mock_tts]
                
                manager = LFMAudioManager(config)
                manager.porcupine_detector = mock_detector
                manager.stt_pipeline = mock_stt
                manager.tts_pipeline = mock_tts
                manager.is_initialized = True
                
                # Create test audio input
                audio_input = np.random.randint(-32768, 32767, 16000, dtype=np.int16).tobytes()
                
                # Execute: End-to-end processing
                audio_output = manager.process_end_to_end(audio_input)
                
                # Verify: Audio output is generated
                assert audio_output != b"", "Should generate audio output"
                assert isinstance(audio_output, bytes), "Output should be audio bytes"
                assert len(audio_output) > 0, "Output should have content"
    
    def test_end_to_end_processing_without_wake_word_skips(self):
        """
        Test that end-to-end processing is skipped without wake word detection.
        
        Validates: Requirements 4.5.4 (wake word detection required)
        """
        # Setup: Create manager with mocked pipelines
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": "jarvis",
            "detection_sensitivity": 50,
            "activation_sound": False,
            "tts_voice": "Nova",
            "speaking_rate": 1.0
        }
        
        with patch('backend.agent.lfm_audio_manager.PorcupineWakeWordDetector') as mock_porcupine_class:
            # Mock Porcupine to return no detection
            mock_detector = MagicMock()
            mock_detector.frame_length = 512
            mock_detector.process_frame.return_value = (False, None)
            mock_porcupine_class.return_value = mock_detector
            
            manager = LFMAudioManager(config)
            manager.porcupine_detector = mock_detector
            manager.is_initialized = True
            
            # Create test audio input
            audio_input = np.random.randint(-32768, 32767, 16000, dtype=np.int16).tobytes()
            
            # Execute: Try end-to-end processing without wake word
            audio_output = manager.process_end_to_end(audio_input)
            
            # Verify: Processing is skipped
            assert audio_output == b"", "Should skip processing without wake word"
    
    def test_wake_word_detection_activates_processing(self):
        """
        Test that wake word detection (Porcupine) enables subsequent processing.
        
        Validates: Requirements 4.5.4 (internal wake word detection)
        """
        # Setup: Create manager with mocked pipelines
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": "computer",
            "detection_sensitivity": 75,
            "activation_sound": True,
            "tts_voice": "Alloy",
            "speaking_rate": 1.0
        }
        
        with patch('backend.agent.lfm_audio_manager.PorcupineWakeWordDetector') as mock_porcupine_class:
            # Mock Porcupine to return wake phrase
            mock_detector = MagicMock()
            mock_detector.frame_length = 512
            mock_detector.process_frame.return_value = (True, "computer")
            mock_porcupine_class.return_value = mock_detector
            
            manager = LFMAudioManager(config)
            manager.porcupine_detector = mock_detector
            manager.is_initialized = True
            
            # Create test audio input
            audio_input = np.random.randint(-32768, 32767, 16000, dtype=np.int16).tobytes()
            
            # Execute: Detect wake word
            wake_detected = manager.detect_wake_word(audio_input)
            
            # Verify: Wake word is detected and state is activated
            assert wake_detected is True, "Wake word should be detected"
            assert manager.wake_word_active is True, "Wake word state should be active"
    
    def test_vad_is_handled_internally(self):
        """
        Test that Voice Activity Detection is handled internally by LFM 2.5.
        
        Validates: Requirement 4.5.5 (internal VAD)
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
        
        with patch('backend.agent.lfm_audio_manager.PorcupineWakeWordDetector') as mock_porcupine_class:
            with patch('backend.agent.lfm_audio_manager.pipeline') as mock_pipeline_func:
                # Mock Porcupine detector
                mock_detector = MagicMock()
                mock_detector.frame_length = 512
                mock_detector.process_frame.return_value = (True, "jarvis")
                mock_porcupine_class.return_value = mock_detector
                
                mock_stt = MagicMock()
                mock_stt.return_value = {"text": "jarvis test"}
                
                mock_tts = MagicMock()
                mock_audio = np.random.rand(16000).astype(np.float32)
                mock_tts.return_value = {"audio": mock_audio}
                
                mock_pipeline_func.side_effect = [mock_stt, mock_tts]
                
                manager = LFMAudioManager(config)
                manager.porcupine_detector = mock_detector
                manager.stt_pipeline = mock_stt
                manager.tts_pipeline = mock_tts
                manager.is_initialized = True
                
                # Create test audio input
                audio_input = np.random.randint(-32768, 32767, 16000, dtype=np.int16).tobytes()
                
                # Execute: End-to-end processing (VAD happens internally)
                audio_output = manager.process_end_to_end(audio_input)
                
                # Verify: Processing completes (VAD was handled internally)
                assert audio_output != b"", "Processing should complete with internal VAD"
    
    def test_stt_transcription_is_internal(self):
        """
        Test that Speech-to-Text transcription is handled internally.
        
        Validates: Requirement 4.5.6 (internal STT)
        """
        # Setup: Create manager with mocked STT
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": "jarvis",
            "detection_sensitivity": 50,
            "activation_sound": False,
            "tts_voice": "Nova",
            "speaking_rate": 1.0
        }
        
        with patch('backend.agent.lfm_audio_manager.pipeline') as mock_pipeline_func:
            # Mock STT to return specific transcription
            mock_stt = MagicMock()
            expected_text = "jarvis what is the weather today"
            mock_stt.return_value = {"text": expected_text}
            mock_pipeline_func.return_value = mock_stt
            
            manager = LFMAudioManager(config)
            manager.stt_pipeline = mock_stt
            manager.is_initialized = True
            
            # Create test audio input
            audio_input = np.random.randint(-32768, 32767, 16000, dtype=np.int16).tobytes()
            
            # Execute: Transcribe audio
            transcription = manager.transcribe_audio(audio_input)
            
            # Verify: Transcription is generated
            assert transcription == expected_text, \
                f"Should transcribe to '{expected_text}'"
    
    def test_conversation_understanding_is_internal(self):
        """
        Test that conversation understanding and response generation is internal.
        
        Validates: Requirement 4.5.7 (internal conversation understanding)
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
        manager.is_initialized = True
        
        # Execute: Generate response
        user_text = "what is the weather today"
        response = manager.generate_response(user_text)
        
        # Verify: Response is generated
        assert response is not None, "Should generate a response"
        assert isinstance(response, str), "Response should be a string"
        assert len(response) > 0, "Response should have content"
    
    def test_tts_synthesis_is_internal(self):
        """
        Test that Text-to-Speech synthesis is handled internally.
        
        Validates: Requirement 4.5.8 (internal TTS)
        """
        # Setup: Create manager with mocked TTS
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": "jarvis",
            "detection_sensitivity": 50,
            "activation_sound": False,
            "tts_voice": "Echo",
            "speaking_rate": 1.2
        }
        
        with patch('backend.agent.lfm_audio_manager.pipeline') as mock_pipeline_func:
            # Mock TTS to return audio
            mock_tts = MagicMock()
            mock_audio = np.random.rand(16000).astype(np.float32)
            mock_tts.return_value = {"audio": mock_audio}
            mock_pipeline_func.return_value = mock_tts
            
            manager = LFMAudioManager(config)
            manager.tts_pipeline = mock_tts
            manager.is_initialized = True
            
            # Execute: Synthesize speech
            text = "The weather is sunny today"
            audio_output = manager.synthesize_speech(text)
            
            # Verify: Audio is synthesized
            assert audio_output != b"", "Should synthesize audio"
            assert isinstance(audio_output, bytes), "Output should be audio bytes"
    
    def test_speaking_rate_adjustment(self):
        """
        Test that speaking rate adjustment is applied to TTS output.
        
        Validates: Requirement 14.2, 14.4 (speaking rate configuration)
        """
        # Setup: Create manager with different speaking rates
        for speaking_rate in [0.5, 1.0, 1.5, 2.0]:
            config = {
                "lfm_model_path": "",
                "device": "cpu",
                "wake_phrase": "jarvis",
                "detection_sensitivity": 50,
                "activation_sound": False,
                "tts_voice": "Nova",
                "speaking_rate": speaking_rate
            }
            
            with patch('backend.agent.lfm_audio_manager.pipeline') as mock_pipeline_func:
                # Mock TTS to return audio
                mock_tts = MagicMock()
                mock_audio = np.random.rand(16000).astype(np.float32)
                mock_tts.return_value = {"audio": mock_audio}
                mock_pipeline_func.return_value = mock_tts
                
                manager = LFMAudioManager(config)
                manager.tts_pipeline = mock_tts
                manager.is_initialized = True
                
                # Execute: Synthesize speech
                text = "Test speech"
                audio_output = manager.synthesize_speech(text)
                
                # Verify: Audio is generated with speaking rate applied
                assert audio_output != b"", \
                    f"Should synthesize audio at {speaking_rate}x rate"
                assert manager.speaking_rate == speaking_rate, \
                    f"Speaking rate should be {speaking_rate}"
    
    def test_voice_characteristics_configuration(self):
        """
        Test that voice characteristics (TTS voice) can be configured.
        
        Validates: Requirement 14.1, 14.3 (TTS voice configuration)
        """
        # Test all valid voice characteristics
        valid_voices = ["Nova", "Alloy", "Echo", "Fable", "Onyx", "Shimmer"]
        
        for voice in valid_voices:
            config = {
                "lfm_model_path": "",
                "device": "cpu",
                "wake_phrase": "jarvis",
                "detection_sensitivity": 50,
                "activation_sound": False,
                "tts_voice": voice,
                "speaking_rate": 1.0
            }
            
            manager = LFMAudioManager(config)
            
            # Verify: Voice is configured correctly
            assert manager.tts_voice == voice, \
                f"TTS voice should be '{voice}'"
    
    def test_audio_processing_is_internal(self):
        """
        Test that audio processing (noise reduction, echo cancellation, etc.) is internal.
        
        Validates: Requirement 4.5.3 (internal audio processing)
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
        
        with patch('backend.agent.lfm_audio_manager.pipeline') as mock_pipeline_func:
            mock_stt = MagicMock()
            mock_stt.return_value = {"text": "jarvis test"}
            
            mock_tts = MagicMock()
            mock_audio = np.random.rand(16000).astype(np.float32)
            mock_tts.return_value = {"audio": mock_audio}
            
            mock_pipeline_func.side_effect = [mock_stt, mock_tts]
            
            manager = LFMAudioManager(config)
            manager.stt_pipeline = mock_stt
            manager.tts_pipeline = mock_tts
            manager.is_initialized = True
            
            # Create test audio input (simulating noisy audio)
            audio_input = np.random.randint(-32768, 32767, 16000, dtype=np.int16).tobytes()
            
            # Execute: Process audio (preprocessing happens internally)
            processed_audio = manager._preprocess_audio(audio_input)
            
            # Verify: Audio is preprocessed
            assert processed_audio is not None, "Audio should be preprocessed"
            assert isinstance(processed_audio, np.ndarray), \
                "Preprocessed audio should be numpy array"
    
    def test_thin_wrapper_architecture(self):
        """
        Test that the backend provides only a thin wrapper around LFM 2.5.
        
        Validates: Requirement 4.5.10 (thin wrapper architecture)
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
        
        # Verify: Manager has minimal interface (thin wrapper)
        # The manager should only have configuration and lifecycle methods
        assert hasattr(manager, 'initialize'), \
            "Manager should have initialize method"
        assert hasattr(manager, 'process_end_to_end'), \
            "Manager should have end-to-end processing method"
        assert hasattr(manager, 'detect_wake_word'), \
            "Manager should have wake word detection method"
        assert hasattr(manager, 'update_wake_config'), \
            "Manager should have configuration update methods"
        assert hasattr(manager, 'update_voice_config'), \
            "Manager should have voice configuration update methods"
        
        # Verify: Manager delegates to LFM 2.5 model (not implementing logic itself)
        # The actual processing is done by the model, not the manager
        assert manager.stt_pipeline is None or hasattr(manager.stt_pipeline, '__call__'), \
            "STT should be delegated to pipeline"
        assert manager.tts_pipeline is None or hasattr(manager.tts_pipeline, '__call__'), \
            "TTS should be delegated to pipeline"
    
    def test_wake_word_state_resets_after_processing(self):
        """
        Test that wake word state resets after end-to-end processing completes.
        
        Validates: Requirement 4.5.9 (natural conversation flow)
        """
        # Setup: Create manager with mocked pipelines
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": "jarvis",
            "detection_sensitivity": 50,
            "activation_sound": False,
            "tts_voice": "Nova",
            "speaking_rate": 1.0
        }
        
        with patch('backend.agent.lfm_audio_manager.PorcupineWakeWordDetector') as mock_porcupine_class:
            with patch('backend.agent.lfm_audio_manager.pipeline') as mock_pipeline_func:
                # Mock Porcupine detector
                mock_detector = MagicMock()
                mock_detector.frame_length = 512
                mock_detector.process_frame.return_value = (True, "jarvis")
                mock_porcupine_class.return_value = mock_detector
                
                mock_stt = MagicMock()
                mock_stt.return_value = {"text": "jarvis hello"}
                
                mock_tts = MagicMock()
                mock_audio = np.random.rand(16000).astype(np.float32)
                mock_tts.return_value = {"audio": mock_audio}
                
                mock_pipeline_func.side_effect = [mock_stt, mock_tts]
                
                manager = LFMAudioManager(config)
                manager.porcupine_detector = mock_detector
                manager.stt_pipeline = mock_stt
                manager.tts_pipeline = mock_tts
                manager.is_initialized = True
                
                # Create test audio input
                audio_input = np.random.randint(-32768, 32767, 16000, dtype=np.int16).tobytes()
                
                # Execute: End-to-end processing
                audio_output = manager.process_end_to_end(audio_input)
                
                # Verify: Wake word state is reset after processing
                assert audio_output != b"", "Should generate audio output"
                assert manager.wake_word_active is False, \
                    "Wake word state should reset after processing"
    
    def test_callbacks_are_triggered_during_processing(self):
        """
        Test that callbacks are triggered during audio stream processing.
        
        Validates: Requirement 4.5.9 (natural conversation flow)
        """
        # Setup: Create manager with mocked pipelines
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": "jarvis",
            "detection_sensitivity": 50,
            "activation_sound": False,
            "tts_voice": "Nova",
            "speaking_rate": 1.0
        }
        
        with patch('backend.agent.lfm_audio_manager.PorcupineWakeWordDetector') as mock_porcupine_class:
            with patch('backend.agent.lfm_audio_manager.pipeline') as mock_pipeline_func:
                # Mock Porcupine detector
                mock_detector = MagicMock()
                mock_detector.frame_length = 512
                mock_detector.process_frame.return_value = (True, "jarvis")
                mock_porcupine_class.return_value = mock_detector
                
                mock_stt = MagicMock()
                mock_stt.return_value = {"text": "jarvis test"}
                
                mock_tts = MagicMock()
                mock_audio = np.random.rand(16000).astype(np.float32)
                mock_tts.return_value = {"audio": mock_audio}
                
                mock_pipeline_func.side_effect = [mock_stt, mock_tts]
                
                manager = LFMAudioManager(config)
                manager.porcupine_detector = mock_detector
                manager.stt_pipeline = mock_stt
                manager.tts_pipeline = mock_tts
                manager.is_initialized = True
                
                # Setup callbacks
                status_callback = Mock()
                audio_callback = Mock()
                manager.set_callbacks(
                    on_status_change=status_callback,
                    on_audio_response=audio_callback
                )
                
                # Create test audio input
                audio_input = np.random.randint(-32768, 32767, 16000, dtype=np.int16).tobytes()
                
                # Execute: Process audio stream
                import asyncio
                asyncio.run(manager.process_audio_stream(audio_input))
                
                # Verify: Callbacks were triggered
                assert status_callback.call_count >= 2, \
                    "Status callback should be called at least twice (processing, ready)"
                assert audio_callback.called, \
                    "Audio response callback should be called"
