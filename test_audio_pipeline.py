import numpy as np
import time
from backend.audio.pipeline import AudioPipeline

def test_audio_capture():
    """Test if audio is actually being captured"""
    print("Testing audio pipeline...")
    
    pipeline = AudioPipeline()
    
    audio_frames = []
    def capture_test(audio_frame):
        rms = np.sqrt(np.mean(audio_frame**2))
        print(f"Captured frame: {len(audio_frame)} samples, RMS: {rms:.6f}")
        audio_frames.append(audio_frame)
    
    pipeline.start(on_audio_frame=capture_test)
    
    print("Recording for 5 seconds... SPEAK INTO YOUR MICROPHONE NOW!")
    time.sleep(5)
    pipeline.stop()
    
    print(f"Total frames captured: {len(audio_frames)}")
    if audio_frames:
        first_frame = audio_frames[0]
        print(f"First frame stats: min={np.min(first_frame):.3f}, max={np.max(first_frame):.3f}, RMS={np.sqrt(np.mean(first_frame**2)):.6f}")
        print(f"Last frame stats: min={np.min(audio_frames[-1]):.3f}, max={np.max(audio_frames[-1]):.3f}, RMS={np.sqrt(np.mean(audio_frames[-1]**2)):.6f}")
    
    return len(audio_frames) > 0

if __name__ == "__main__":
    success = test_audio_capture()
    print(f"Audio capture test: {'PASSED' if success else 'FAILED'}")
    if not success:
        print("\nTROUBLESHOOTING:")
        print("1. Check if microphone is connected and enabled")
        print("2. Check if other applications are using the microphone")
        print("3. Check system permissions for microphone access")
        print("4. Try selecting a different input device")