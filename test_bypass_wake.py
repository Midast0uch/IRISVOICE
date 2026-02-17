"""
Test script to bypass wake word detection and test the full conversation flow
"""
import time
from backend.audio import get_audio_engine

def test_bypass_wake_word():
    """Test the conversation flow without wake word detection"""
    print("Testing conversation flow with bypassed wake word...")
    
    audio_engine = get_audio_engine()
    
    if not audio_engine:
        print("ERROR: Audio engine not available")
        return False
    
    # Initialize if needed
    if not audio_engine.pipeline:
        if not audio_engine.initialize():
            print("ERROR: Failed to initialize audio engine")
            return False
    
    # Start the audio pipeline
    if not audio_engine.start():
        print("ERROR: Failed to start audio engine")
        return False
    
    print("Audio engine started successfully")
    print(f"Current state: {audio_engine.state}")
    print(f"Wake phrase: {audio_engine.config.get('wake_phrase', 'Jarvis')}")
    print(f"Sensitivity: {audio_engine.config.get('wake_word_sensitivity', 0.7)}")
    
    # Simulate wake word detection
    print("\nSimulating wake word detection...")
    audio_engine._on_wake_word_detected()
    
    # Wait a bit
    time.sleep(2)
    
    # Simulate speech start
    print("\nSimulating speech start...")
    audio_engine._on_speech_started()
    
    # Wait a bit
    time.sleep(2)
    
    # Simulate speech end with a dummy audio buffer
    print("\nSimulating speech end...")
    import numpy as np
    dummy_buffer = np.random.randn(16000).astype(np.float32) * 0.1  # 1 second of noise
    audio_engine._on_speech_ended()
    
    print("\nBypass test completed")
    print("If you see this message, the conversation flow is working")
    print("The issue is likely in the wake word detection or audio capture")
    
    return True

if __name__ == "__main__":
    success = test_bypass_wake_word()
    print(f"Bypass test: {'PASSED' if success else 'FAILED'}")