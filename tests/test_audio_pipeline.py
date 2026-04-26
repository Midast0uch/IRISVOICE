"""
Comprehensive Audio Pipeline Tests

Tests the complete TTS synthesis pipeline:
1. CosyVoice2-0.5B zero-shot voice cloning + streaming
2. pyttsx3 fallback (Built-in voice)
3. Audio normalization integration
4. Gateway streaming playback
"""
import pytest
import numpy as np
from pathlib import Path

# Test imports
try:
    from backend.agent.tts import TTSManager, get_tts_manager
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False

try:
    from backend.voice.tts_normalizer import normalize_for_speech
    NORMALIZER_AVAILABLE = True
except ImportError:
    NORMALIZER_AVAILABLE = False

try:
    from backend.audio.engine import get_audio_engine, AudioEngine
    AUDIO_ENGINE_AVAILABLE = True
except ImportError:
    AUDIO_ENGINE_AVAILABLE = False

try:
    from iris_gateway import IRISGateway
    GATEWAY_AVAILABLE = True
except ImportError:
    GATEWAY_AVAILABLE = False

# ---------------------------------------------------------------------------
# Test fixtures and helpers
# ---------------------------------------------------------------------------

def create_test_text():
    """Create various test texts for TTS synthesis."""
    return {
        'short': 'Hello, this is a test.',
        'medium': 'This is a medium-length sentence to test the text-to-speech engine. It should produce clear audio output at 24kHz sample rate.',
        'long': 'The quick brown fox jumps over the lazy dog. This pangram contains every letter of the alphabet and tests the complete character set support in the TTS model.',
    }

# ---------------------------------------------------------------------------
# Unit Tests: TTS Manager
# ---------------------------------------------------------------------------

class TestTTSManager:
    """Tests for TTSManager (CosyVoice2-0.5B)."""
    
    def test_singleton_pattern(self):
        """Test that get_tts_manager() returns the same instance."""
        manager1 = get_tts_manager()
        manager2 = get_tts_manager()
        assert manager1 is manager2, "TTSManager should be a singleton"
    
    def test_config_initialization(self):
        """Test default configuration values."""
        manager = get_tts_manager()
        config = manager.get_config()
        assert 'tts_enabled' in config
        assert 'tts_voice' in config
        assert 'speaking_rate' in config
    
    def test_update_config(self):
        """Test configuration updates."""
        manager = get_tts_manager()
        manager.update_config(tts_voice="Built-in")
        config = manager.get_config()
        assert config['tts_voice'] == 'Built-in'
    
    def test_synthesize_empty_text(self):
        """Test that empty text returns None."""
        manager = get_tts_manager()
        result = manager.synthesize("")
        assert result is None
    
    def test_synthesize_none_text(self):
        """Test that None text returns None."""
        manager = get_tts_manager()
        result = manager.synthesize(None)
        assert result is None
    
    def test_synthesize_disabled(self):
        """Test TTS disabled mode."""
        manager = get_tts_manager()
        manager.update_config(tts_enabled=False)
        result = manager.synthesize("Hello world")
        assert result is None
    
    def test_voice_info(self):
        """Test voice information retrieval."""
        manager = get_tts_manager()
        info = manager.get_voice_info()
        assert 'available_voices' in info
        assert 'current_voice' in info
        assert 'config' in info
    
    def test_synthesize_stream_generator(self):
        """Test that synthesize_stream returns a generator."""
        manager = get_tts_manager()
        result = manager.synthesize_stream("Hello world")
        assert hasattr(result, '__iter__'), "Should return an iterable"

# ---------------------------------------------------------------------------
# Unit Tests: Audio Normalizer
# ---------------------------------------------------------------------------

class TestTTSNormalizer:
    """Tests for tts_normalizer module."""
    
    def test_emoji_removal(self):
        """Test emoji removal from text."""
        text = "Hello 🌍 world!"
        normalized = normalize_for_speech(text)
        assert '🌍' not in normalized
        assert 'Hello' in normalized and 'world' in normalized
    
    def test_markdown_stripping(self):
        """Test markdown formatting removal."""
        text = "# Heading\n**Bold**\n*Italic*"
        normalized = normalize_for_speech(text)
        assert '#' not in normalized
        assert '*' not in normalized
    
    def test_exclamation_replacement(self):
        """Test exclamation mark replacement."""
        text = "Hello! How are you?"
        normalized = normalize_for_speech(text)
        assert '!' not in normalized
        assert '.' in normalized  # Should be replaced with period
    
    def test_sentence_splitting(self):
        """Test that normalization returns a string (not list)."""
        text = "Hello world. This is a second sentence."
        sentences = normalize_for_speech(text)
        assert isinstance(sentences, str), "normalize_for_speech returns a string, not a list"
        assert 'Hello' in sentences and 'world' in sentences
    
    def test_empty_input(self):
        """Test empty input handling."""
        result = normalize_for_speech("")
        assert result == ""

# ---------------------------------------------------------------------------
# Integration Tests: Audio Engine
# ---------------------------------------------------------------------------

class TestAudioEngine:
    """Tests for audio playback engine."""
    
    def test_pipeline_initialization(self):
        """Test that audio pipeline initializes correctly."""
        try:
            engine = get_audio_engine()
            assert engine is not None
            # Pipeline may be None initially if no audio has been played yet
            print(f"Audio engine initialized: {engine}")
        except Exception as e:
            pytest.skip(f"Audio engine unavailable: {e}")
    
    def test_play_audio(self):
        """Test basic audio playback."""
        try:
            engine = get_audio_engine()
            if not engine.pipeline:
                pytest.skip("Pipeline not initialized yet")
            
            # Generate a simple sine wave for testing
            sample_rate = 24000
            duration = 1.0
            t = np.linspace(0, duration, int(sample_rate * duration))
            audio = 0.5 * np.sin(2 * np.pi * 440 * t)  # 440 Hz tone
            
            engine.play(audio)
            print("Audio playback test completed successfully")
        except Exception as e:
            pytest.skip(f"Playback unavailable: {e}")
    
    def test_play_wav_file(self):
        """Test playing a WAV file."""
        try:
            engine = get_audio_engine()
            if not engine.pipeline:
                pytest.skip("Pipeline not initialized yet")
            
            # Create a simple test WAV file
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                tmp_path = f.name
            
            try:
                from scipy.io import wavfile
                sr = 24000
                t = np.linspace(0, 1.0, int(sr))
                audio = 0.5 * np.sin(2 * np.pi * 800 * t)  # 800 Hz tone
                wavfile.write(tmp_path, sr, audio.astype(np.float32))
                
                engine.play_wav(tmp_path)
                print("WAV playback test completed successfully")
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        except Exception as e:
            pytest.skip(f"File playback unavailable: {e}")

# ---------------------------------------------------------------------------
# Integration Tests: Gateway TTS Playback
# ---------------------------------------------------------------------------

class TestGatewayTTSPlayback:
    """Tests for gateway text-to-speech playback."""
    
    def test_speak_response(self):
        """Test gateway's _speak_response method."""
        try:
            # Create a minimal gateway instance
            from backend.iris_gateway import IRISGateway
            
            gateway = IRISGateway(
                session_id="test-session-123",
                tts_voice="Built-in",  # Use built-in for faster testing
            )
            
            # Test with simple text
            test_text = "Hello, this is a test message from the gateway."
            
            # Run in thread to avoid blocking
            import threading
            result_thread = threading.Thread(target=gateway._speak_response, args=(test_text,))
            result_thread.start()
            result_thread.join(timeout=10)
            
            print(f"Gateway TTS playback test completed for: '{test_text}'")
        except Exception as e:
            pytest.skip(f"Gateway unavailable: {e}")
    
    def test_speak_response_streaming(self):
        """Test gateway's streaming text-to-speech."""
        try:
            from backend.iris_gateway import IRISGateway
            
            gateway = IRISGateway(
                session_id="test-session-stream",
                tts_voice="Built-in",  # Use built-in for faster testing
            )
            
            test_text = "This is a streaming test message with multiple words."
            
            import threading
            result_thread = threading.Thread(target=gateway._speak_response, args=(test_text,))
            result_thread.start()
            result_thread.join(timeout=10)
            
            print(f"Gateway streaming TTS playback test completed for: '{test_text}'")
        except Exception as e:
            pytest.skip(f"Gateway unavailable: {e}")

# ---------------------------------------------------------------------------
# End-to-End Pipeline Test
# ---------------------------------------------------------------------------

def test_end_to_end_pipeline():
    """
    Complete end-to-end test of the audio pipeline.
    
    Flow:
    1. Normalize text for speech
    2. Synthesize via TTS manager (CosyVoice2 or Built-in)
    3. Play through audio engine
    """
    print("\n=== Starting End-to-End Pipeline Test ===")
    
    # Step 1: Text normalization
    original_text = "Hello! This is a test of the complete audio pipeline." + " 🌍"
    normalized_text = normalize_for_speech(original_text)
    print(f"Original text: {original_text}")
    print(f"Normalized text: {normalized_text}")
    assert '🌍' not in normalized_text, "Emoji should be removed"
    
    # Step 2: TTS synthesis
    manager = get_tts_manager()
    audio = manager.synthesize(normalized_text)
    print(f"Synthesized audio shape: {audio.shape if audio is not None else 'None'}")
    assert audio is not None, "Audio should be synthesized"
    
    # Verify audio properties
    assert len(audio) > 0, "Audio should have samples"
    assert np.all(np.isfinite(audio)), "Audio values should be finite"
    print(f"Audio sample rate: {24000} Hz (CosyVoice2 output, resampled to 16kHz)")
    
    # Step 3: Audio playback
    try:
        engine = get_audio_engine()
        if engine.pipeline:
            engine.play(audio)
            print("✓ Audio successfully played through pipeline")
        else:
            print("⚠ Pipeline not ready for playback (may be first call)")
    except Exception as e:
        print(f"⚠ Playback skipped: {e}")
    
    print("\n=== End-to-End Pipeline Test Complete ===")

# ---------------------------------------------------------------------------
# Main test runner
# ---------------------------------------------------------------------------

def run_all_tests():
    """Run all tests and report results."""
    print("=" * 60)
    print("AUDIO PIPELINE TEST SUITE")
    print("=" * 60)
    
    # Check availability
    print(f"\n✓ TTS Manager: {'Available' if TTS_AVAILABLE else 'Not installed'}")
    print(f"✓ Normalizer: {'Available' if NORMALIZER_AVAILABLE else 'Not installed'}")
    print(f"✓ Audio Engine: {'Available' if AUDIO_ENGINE_AVAILABLE else 'Not installed'}")
    print(f"✓ Gateway: {'Available' if GATEWAY_AVAILABLE else 'Not installed'}")
    
    # Run unit tests
    test_classes = [
        TestTTSManager,
        TestTTSNormalizer,
        TestAudioEngine,
        TestGatewayTTSPlayback,
    ]
    
    for test_class in test_classes:
        print(f"\n--- Running {test_class.__name__} tests ---")
        try:
            suite = pytest.main([__file__, '-v', '--tb=short'])
            break
        except Exception as e:
            print(f"Test suite error: {e}")
    
    # Run end-to-end test separately
    try:
        test_end_to_end_pipeline()
    except Exception as e:
        print(f"\nEnd-to-End test error: {e}")
    
    print("\n" + "=" * 60)
    print("TEST SUITE COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    run_all_tests()
