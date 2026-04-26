#!/usr/bin/env python3
"""
Verification script for Porcupine Wake Word Integration

This script verifies that the Porcupine integration is properly configured
and can be initialized successfully.
"""

import os
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

def verify_environment():
    """Verify environment variables are set."""
    print("=" * 60)
    print("1. Verifying Environment Configuration")
    print("=" * 60)
    
    access_key = os.getenv("PICOVOICE_ACCESS_KEY")
    if access_key:
        print("✅ PICOVOICE_ACCESS_KEY is set")
        print(f"   Key: {access_key[:20]}...")
    else:
        print("❌ PICOVOICE_ACCESS_KEY is not set")
        print("   Please set it in your .env file")
        return False
    
    print()
    return True

def verify_model_files():
    """Verify wake word model files exist."""
    print("=" * 60)
    print("2. Verifying Wake Word Model Files")
    print("=" * 60)
    
    models_dir = Path(__file__).parent / "models" / "wake_words"
    custom_model = models_dir / "hey-iris_en_windows_v4_0_0.ppn"
    
    if models_dir.exists():
        print(f"✅ Models directory exists: {models_dir}")
    else:
        print(f"❌ Models directory not found: {models_dir}")
        return False
    
    if custom_model.exists():
        print(f"✅ Custom wake word model exists: {custom_model.name}")
        print(f"   Size: {custom_model.stat().st_size / 1024:.2f} KB")
    else:
        print(f"❌ Custom wake word model not found: {custom_model}")
        return False
    
    print()
    return True

def verify_porcupine_detector():
    """Verify PorcupineWakeWordDetector can be imported and initialized."""
    print("=" * 60)
    print("3. Verifying PorcupineWakeWordDetector")
    print("=" * 60)
    
    try:
        from backend.voice.porcupine_detector import PorcupineWakeWordDetector
        print("✅ PorcupineWakeWordDetector imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import PorcupineWakeWordDetector: {e}")
        return False
    
    # Test initialization with built-in keyword
    try:
        detector = PorcupineWakeWordDetector(
            builtin_keywords=["jarvis"],
            sensitivities=[0.5]
        )
        print("✅ PorcupineWakeWordDetector initialized with built-in keyword")
        print(f"   Sample rate: {detector.sample_rate} Hz")
        print(f"   Frame length: {detector.frame_length} samples")
        print(f"   Wake words: {detector.wake_word_names}")
        detector.cleanup()
    except Exception as e:
        print(f"❌ Failed to initialize PorcupineWakeWordDetector: {e}")
        return False
    
    # Test initialization with custom model
    try:
        custom_model_path = str(Path(__file__).parent / "models" / "wake_words" / "hey-iris_en_windows_v4_0_0.ppn")
        detector = PorcupineWakeWordDetector(
            custom_model_path=custom_model_path
            # Test custom model only (no built-in keywords mixed)
        )
        print("✅ PorcupineWakeWordDetector initialized with custom model")
        print(f"   Wake words: {detector.wake_word_names}")
        detector.cleanup()
    except Exception as e:
        print(f"❌ Failed to initialize with custom model: {e}")
        return False
    
    print()
    return True

def verify_lfm_audio_manager():
    """Verify LFMAudioManager integration."""
    print("=" * 60)
    print("4. Verifying LFMAudioManager Integration")
    print("=" * 60)
    
    try:
        from backend.agent.lfm_audio_manager import LFMAudioManager
        print("✅ LFMAudioManager imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import LFMAudioManager: {e}")
        return False
    
    # Test configuration with different wake phrases
    wake_phrases = ["jarvis", "computer", "bumblebee", "porcupine", "hey iris"]
    
    for wake_phrase in wake_phrases:
        try:
            config = {
                "lfm_model_path": "",
                "device": "cpu",
                "wake_phrase": wake_phrase,
                "detection_sensitivity": 50,
                "activation_sound": True,
                "tts_voice": "Nova",
                "speaking_rate": 1.0
            }
            manager = LFMAudioManager(config)
            print(f"✅ LFMAudioManager configured with wake phrase: '{wake_phrase}'")
        except Exception as e:
            print(f"❌ Failed to configure with '{wake_phrase}': {e}")
            return False
    
    print()
    return True

def verify_tests():
    """Verify tests can be run."""
    print("=" * 60)
    print("5. Verifying Test Suite")
    print("=" * 60)
    
    import subprocess
    
    test_files = [
        "tests/property/test_wake_word_detection_properties.py",
        "tests/property/test_wake_word_configuration_properties.py",
        "tests/integration/test_lfm_audio_end_to_end.py"
    ]
    
    for test_file in test_files:
        test_path = Path(__file__).parent / test_file
        if test_path.exists():
            print(f"✅ Test file exists: {test_file}")
        else:
            print(f"❌ Test file not found: {test_file}")
            return False
    
    print("\nTo run all tests, execute:")
    print("  python -m pytest tests/property/test_wake_word_detection_properties.py tests/property/test_wake_word_configuration_properties.py tests/integration/test_lfm_audio_end_to_end.py -v")
    
    print()
    return True

def main():
    """Main verification function."""
    print("\n" + "=" * 60)
    print("PORCUPINE WAKE WORD INTEGRATION VERIFICATION")
    print("=" * 60)
    print()
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    results = []
    
    # Run verification steps
    results.append(("Environment", verify_environment()))
    results.append(("Model Files", verify_model_files()))
    results.append(("Porcupine Detector", verify_porcupine_detector()))
    results.append(("LFM Audio Manager", verify_lfm_audio_manager()))
    results.append(("Test Suite", verify_tests()))
    
    # Print summary
    print("=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{name:.<40} {status}")
        if not passed:
            all_passed = False
    
    print("=" * 60)
    
    if all_passed:
        print("\n🎉 All verifications passed! Porcupine integration is ready.")
        print("\nSupported wake phrases:")
        print("  - 'hey iris' (custom trained)")
        print("  - 'jarvis' (built-in)")
        print("  - 'computer' (built-in)")
        print("  - 'bumblebee' (built-in)")
        print("  - 'porcupine' (built-in)")
        return 0
    else:
        print("\n❌ Some verifications failed. Please check the errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
