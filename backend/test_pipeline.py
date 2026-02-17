"""
IRIS Voice Pipeline End-to-End Test
Tests the complete audio flow without requiring actual hardware
"""
import asyncio
import sys
import numpy as np
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

def test_model_manager():
    """Test LFM 2.5 model manager"""
    print("\n=== Testing ModelManager ===")
    from audio.model_manager import ModelManager
    
    manager = ModelManager()
    info = manager.get_info()
    
    print(f"Model directory: {info['model_dir']}")
    print(f"Downloaded: {info['downloaded']}")
    print(f"Loaded: {info['loaded']}")
    
    if info['downloaded']:
        print(f"Model size: {info.get('size_mb', 'N/A')} MB")
    else:
        print("Model not downloaded yet (expected on fresh install)")
    
    return True

def test_audio_engine():
    """Test AudioEngine initialization"""
    print("\n=== Testing AudioEngine ===")
    from audio.engine import AudioEngine, VoiceState
    
    engine = AudioEngine()
    
    print(f"Initial state: {engine.state}")
    print(f"Config: {engine.config}")
    
    # Test state callbacks
    states_captured = []
    def on_state_change(state):
        states_captured.append(state)
    
    engine.on_state_change(on_state_change)
    
    # Test manual state transition
    engine._set_state(VoiceState.LISTENING)
    assert VoiceState.LISTENING in states_captured
    print(f"State transition captured: {states_captured}")
    
    # Reset
    engine._set_state(VoiceState.IDLE)
    
    print("AudioEngine: OK")
    return True

def test_personality_engine():
    """Test PersonalityEngine"""
    print("\n=== Testing PersonalityEngine ===")
    from agent.personality import get_personality_engine
    
    engine = get_personality_engine()
    
    profile = engine.get_profile()
    print(f"Profile: {profile}")
    
    system_prompt = engine.get_system_prompt()
    print(f"System prompt preview: {system_prompt[:100]}...")
    
    # Test update
    engine.update_profile(assistant_name="TestBot", personality="Technical")
    assert engine.profile.assistant_name == "TestBot"
    assert engine.profile.personality == "Technical"
    
    print("PersonalityEngine: OK")
    return True

def test_wake_config():
    """Test WakeConfig"""
    print("\n=== Testing WakeConfig ===")
    from agent.wake_config import get_wake_config
    
    config = get_wake_config()
    
    print(f"Wake phrase: {config.get_wake_phrase()}")
    print(f"Sensitivity: {config.get_sensitivity()}")
    print(f"Supported phrases: {config.SUPPORTED_PHRASES}")
    
    # Test update
    config.update_config(detection_sensitivity=0.5, sleep_timeout=30)
    assert config.get_sensitivity() == 0.5
    assert config.get_sleep_timeout() == 30
    
    print("WakeConfig: OK")
    return True

def test_conversation_memory():
    """Test ConversationMemory"""
    print("\n=== Testing ConversationMemory ===")
    from agent.memory import get_conversation_memory, Message
    
    memory = get_conversation_memory()
    memory.clear()
    
    # Add messages
    memory.add_message("user", "Hello", text_tokens=10)
    memory.add_message("assistant", "Hi there!", text_tokens=15)
    
    print(f"Token count: {memory.get_token_count()}")
    print(f"Context window: {len(memory.get_context_window())} messages")
    
    # Test visualization
    viz = memory.get_context_visualization()
    print(f"Visualization: {viz}")
    
    memory.clear()
    print("ConversationMemory: OK")
    return True

def test_tts_manager():
    """Test TTSManager (without OpenAI API call)"""
    print("\n=== Testing TTSManager ===")
    from agent.tts import get_tts_manager
    
    tts = get_tts_manager()
    
    config = tts.get_config()
    print(f"TTS Config: {config}")
    
    voice_info = tts.get_voice_info()
    print(f"Available voices: {voice_info['available_voices']}")
    
    # Test pitch shift (no API call needed)
    test_audio = np.sin(2 * np.pi * 440 * np.linspace(0, 1, 24000))  # 1 second sine wave
    shifted = tts.apply_pitch_shift(test_audio, 2)
    assert len(shifted) == len(test_audio)
    
    print("TTSManager: OK (pitch shift works)")
    return True

def test_audio_tokenizer():
    """Test AudioTokenizer"""
    print("\n=== Testing AudioTokenizer ===")
    from audio.tokenizer import AudioTokenizer
    
    tokenizer = AudioTokenizer()
    
    # Test with dummy audio
    dummy_audio = np.random.randn(16000) * 0.1  # 1 second of noise
    
    # Encode
    tokens = tokenizer.encode(dummy_audio)
    print(f"Encoded {len(dummy_audio)} samples to {len(tokens)} tokens")
    
    # Decode
    decoded = tokenizer.decode(tokens)
    print(f"Decoded back to {len(decoded)} samples")
    
    print("AudioTokenizer: OK")
    return True

def test_power_manager():
    """Test PowerManager (without actually shutting down)"""
    print("\n=== Testing PowerManager ===")
    from system.power import get_power_manager, PowerProfile
    
    power = get_power_manager()
    
    status = power.get_status()
    print(f"Platform: {status['platform']}")
    print(f"Power profile: {status['power_profile']}")
    print(f"Battery: {status['battery']}")
    
    # Test profile switching (without actually changing)
    print(f"Available profiles: {[p.value for p in PowerProfile]}")
    
    print("PowerManager: OK")
    return True

def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("IRIS Backend Component Tests")
    print("=" * 60)
    
    tests = [
        ("ModelManager", test_model_manager),
        ("AudioEngine", test_audio_engine),
        ("PersonalityEngine", test_personality_engine),
        ("WakeConfig", test_wake_config),
        ("ConversationMemory", test_conversation_memory),
        ("TTSManager", test_tts_manager),
        ("AudioTokenizer", test_audio_tokenizer),
        ("PowerManager", test_power_manager),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
                print(f"❌ {name} failed")
        except Exception as e:
            failed += 1
            print(f"❌ {name} error: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
