import numpy as np
import time
from backend.audio.wake_word import WakeWordDetector

def test_wake_word():
    """Test wake word detector with synthetic audio"""
    print("Testing wake word detector...")
    
    detector = WakeWordDetector(sensitivity=0.5, wake_phrase="Jarvis")
    
    if not detector.initialize():
        print("FAILED: Wake word detector failed to initialize")
        print("Check if openwakeword is installed: pip install openwakeword")
        return False
    
    print("Wake word detector initialized successfully!")
    print("Testing with silence (should return False)...")
    
    # Test with silence
    silence = np.zeros(1600, dtype=np.float32)  # 100ms of silence
    result = detector.process(silence)
    print(f"Silence detection: {result} (should be False)")
    
    print("Testing with random noise (should return False)...")
    # Test with random noise
    noise = np.random.randn(1600).astype(np.float32) * 0.1
    result = detector.process(noise)
    print(f"Noise detection: {result} (should be False)")
    
    print("Testing with multiple noise frames...")
    # Test multiple frames
    for i in range(10):
        noise = np.random.randn(1600).astype(np.float32) * 0.1
        result = detector.process(noise)
        print(f"Frame {i+1}: detection={result}")
    
    print("Wake word detector test completed")
    return True

if __name__ == "__main__":
    success = test_wake_word()
    print(f"Wake word detector test: {'PASSED' if success else 'FAILED'}")