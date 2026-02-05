"""
IRIS Backend Component Tests (Offline - No Model Downloads)
Tests core functionality without requiring network or large models
"""
import sys
import numpy as np
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

def test_audio_engine():
    """Test AudioEngine initialization and state management"""
    print("\n=== Testing AudioEngine ===")
    from audio.engine import AudioEngine, VoiceState
    
    engine = AudioEngine()
    
    print(f"Initial state: {engine.state}")
    assert engine.state == VoiceState.IDLE
    
    # Test state callbacks
    states_captured = []
    def on_state_change(state):
        states_captured.append(state)
    
    engine.on_state_change(on_state_change)
    
    # Test manual state transitions
    engine._set_state(VoiceState.LISTENING)
    assert VoiceState.LISTENING in states_captured
    
    engine._set_state(VoiceState.PROCESSING_CONVERSATION)
    assert VoiceState.PROCESSING_CONVERSATION in states_captured
    
    engine._set_state(VoiceState.IDLE)
    
    print(f"State transitions: {[s.value for s in states_captured]}")
    print("AudioEngine: OK")
    return True

def test_personality_engine():
    """Test PersonalityEngine"""
    print("\n=== Testing PersonalityEngine ===")
    from agent.personality import get_personality_engine
    
    engine = get_personality_engine()
    
    profile = engine.get_profile()
    print(f"Default profile: {profile}")
    
    system_prompt = engine.get_system_prompt()
    assert "IRIS" in system_prompt
    print(f"System prompt generated: {len(system_prompt)} chars")
    
    # Test update
    engine.update_profile(assistant_name="TestBot", personality="Technical", knowledge="Coding")
    assert engine.profile.assistant_name == "TestBot"
    
    new_prompt = engine.get_system_prompt()
    assert "TestBot" in new_prompt
    assert "Technical" in new_prompt or "analytical" in new_prompt.lower()
    
    print("PersonalityEngine: OK")
    return True

def test_wake_config():
    """Test WakeConfig"""
    print("\n=== Testing WakeConfig ===")
    from agent.wake_config import get_wake_config
    
    config = get_wake_config()
    
    print(f"Default wake phrase: {config.get_wake_phrase()}")
    print(f"Default sensitivity: {config.get_sensitivity()}")
    print(f"Supported: {config.SUPPORTED_PHRASES}")
    
    # Test bounds validation
    config.update_config(detection_sensitivity=0.5, sleep_timeout=30)
    assert config.get_sensitivity() == 0.5
    assert config.get_sleep_timeout() == 30
    
    # Test clamping
    config.update_config(detection_sensitivity=2.0)  # Should clamp to 1.0
    assert config.get_sensitivity() == 1.0
    
    config.update_config(detection_sensitivity=-1.0)  # Should clamp to 0.0
    assert config.get_sensitivity() == 0.0
    
    print("WakeConfig: OK")
    return True

def test_conversation_memory():
    """Test ConversationMemory"""
    print("\n=== Testing ConversationMemory ===")
    from agent.memory import get_conversation_memory
    
    memory = get_conversation_memory()
    memory.clear()
    
    # Add messages
    memory.add_message("user", "Hello IRIS", text_tokens=10, audio_tokens=5)
    memory.add_message("assistant", "Hello! How can I help?", text_tokens=15, audio_tokens=8)
    memory.add_message("user", "What's the weather?", text_tokens=12, audio_tokens=6)
    
    print(f"Total tokens: {memory.get_token_count()}")
    print(f"Message count: {len(memory.messages)}")
    
    # Test context window
    context = memory.get_context_window()
    assert len(context) == 3
    
    # Test pruning (set low limit)
    memory.max_context_tokens = 20
    memory._prune_if_needed()
    print(f"After pruning: {len(memory.messages)} messages")
    
    # Reset for other tests
    memory.clear()
    memory.max_context_tokens = 8192
    
    print("ConversationMemory: OK")
    return True

def test_tts_manager():
    """Test TTSManager configuration"""
    print("\n=== Testing TTSManager ===")
    from agent.tts import get_tts_manager
    
    tts = get_tts_manager()
    
    config = tts.get_config()
    print(f"Voice: {config['tts_voice']}")
    print(f"Speaking rate: {config['speaking_rate']}")
    print(f"Pitch adjustment: {config['pitch_adjustment']}")
    
    voice_info = tts.get_voice_info()
    assert len(voice_info['available_voices']) == 6
    
    # Test config update
    tts.update_config(tts_voice="Alloy", speaking_rate=1.2)
    assert tts.get_config()['tts_voice'] == "Alloy"
    assert tts.get_config()['speaking_rate'] == 1.2
    
    print("TTSManager: OK")
    return True

def test_power_manager():
    """Test PowerManager"""
    print("\n=== Testing PowerManager ===")
    from system.power import get_power_manager, PowerProfile
    
    power = get_power_manager()
    
    status = power.get_status()
    print(f"Platform: {status['platform']}")
    print(f"Current profile: {status['power_profile']}")
    
    battery = power.get_battery_status()
    print(f"Battery info: {battery}")
    
    # Test profile enum
    assert PowerProfile.BALANCED.value == "Balanced"
    assert PowerProfile.PERFORMANCE.value == "Performance"
    
    print("PowerManager: OK")
    return True

def test_display_manager():
    """Test DisplayManager"""
    print("\n=== Testing DisplayManager ===")
    from system.display import get_display_manager
    
    display = get_display_manager()
    
    print(f"Current brightness: {display.get_brightness()}")
    
    # Test brightness bounds
    result = display.set_brightness(150)  # Should clamp to 100
    assert display.get_brightness() == 100
    
    result = display.set_brightness(-10)  # Should clamp to 0
    assert display.get_brightness() == 0
    
    result = display.set_brightness(50)
    assert display.get_brightness() == 50
    
    monitors = display.get_monitors()
    print(f"Monitors detected: {len(monitors)}")
    
    print("DisplayManager: OK")
    return True

def test_storage_manager():
    """Test StorageManager"""
    print("\n=== Testing StorageManager ===")
    from system.storage import get_storage_manager
    
    storage = get_storage_manager()
    
    # Test disk usage for current directory
    usage = storage.get_disk_usage(".")
    if usage.get('success'):
        print(f"Current dir - Total: {usage['total_gb']} GB, Free: {usage['free_gb']} GB")
    
    # Test quick folders
    folders = storage.get_quick_folders()
    for name, info in folders.items():
        status = "✓" if info.get('exists') else "✗"
        print(f"  {name}: {status}")
    
    drives = storage.get_all_drives()
    print(f"Drives found: {len(drives)}")
    
    print("StorageManager: OK")
    return True

def test_network_manager():
    """Test NetworkManager"""
    print("\n=== Testing NetworkManager ===")
    from system.network import get_network_manager, VPNType
    
    network = get_network_manager()
    
    wifi = network.get_wifi_status()
    print(f"WiFi enabled: {wifi.get('enabled', 'N/A')}")
    
    ethernet = network.get_ethernet_status()
    print(f"Ethernet connected: {ethernet.get('connected', 'N/A')}")
    
    # Test VPN enum
    assert VPNType.NONE.value == "None"
    assert VPNType.WORK.value == "Work"
    
    connection_test = network.test_connection("8.8.8.8", timeout=2)
    print(f"Internet connectivity: {connection_test.get('connected', 'unknown')}")
    
    print("NetworkManager: OK")
    return True

def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("IRIS Backend Component Tests (Offline)")
    print("=" * 60)
    
    tests = [
        ("AudioEngine", test_audio_engine),
        ("PersonalityEngine", test_personality_engine),
        ("WakeConfig", test_wake_config),
        ("ConversationMemory", test_conversation_memory),
        ("TTSManager", test_tts_manager),
        ("PowerManager", test_power_manager),
        ("DisplayManager", test_display_manager),
        ("StorageManager", test_storage_manager),
        ("NetworkManager", test_network_manager),
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
    
    if failed == 0:
        print("\n✅ All core components functional!")
    
    return failed == 0

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
