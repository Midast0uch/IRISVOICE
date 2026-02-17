"""
Phase 1 Dependency Checker
Verifies all required dependencies for Phase 1 voice feature are installed
"""

import sys
import os

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    os.system('chcp 65001 > nul')

def check_dependency(module_name, import_name=None, description=""):
    """Check if a dependency is installed"""
    if import_name is None:
        import_name = module_name
    
    try:
        __import__(import_name)
        print(f"[OK] {module_name:25} - {description}")
        return True
    except ImportError as e:
        print(f"[MISSING] {module_name:25} - {description}")
        print(f"          Error: {e}")
        return False

def main():
    print("=" * 70)
    print("Phase 1 Dependency Check")
    print("=" * 70)
    print()
    
    print(f"Python Version: {sys.version}")
    print()
    
    # Core dependencies
    print("Core Dependencies:")
    print("-" * 70)
    core_deps = [
        ("fastapi", "fastapi", "Web framework"),
        ("uvicorn", "uvicorn", "ASGI server"),
        ("websockets", "websockets", "WebSocket support"),
        ("pydantic", "pydantic", "Data validation"),
        ("numpy", "numpy", "Numerical computing"),
    ]
    
    core_ok = all(check_dependency(*dep) for dep in core_deps)
    print()
    
    # Audio dependencies
    print("Audio Dependencies:")
    print("-" * 70)
    audio_deps = [
        ("pyaudio", "pyaudio", "Audio I/O"),
        ("scipy", "scipy", "Signal processing"),
        ("pvporcupine", "pvporcupine", "Wake word detection"),
        ("silero-vad", "silero_vad", "Voice activity detection"),
        ("llama-cpp-python", "llama_cpp", "Local LLM"),
        ("speechrecognition", "speech_recognition", "Speech recognition"),
        ("whisper", "whisper", "OpenAI Whisper STT"),
        ("pydub", "pydub", "Audio manipulation"),
    ]
    
    audio_ok = all(check_dependency(*dep) for dep in audio_deps)
    print()
    
    # Backend modules
    print("Backend Modules:")
    print("-" * 70)
    backend_deps = [
        ("backend.audio", "backend.audio", "Audio engine"),
        ("backend.audio.pipeline", "backend.audio.pipeline", "Audio pipeline"),
        ("backend.audio.vad", "backend.audio.vad", "VAD processor"),
        ("backend.audio.voice_command", "backend.audio.voice_command", "Voice command handler"),
        ("backend.audio.engine", "backend.audio.engine", "Audio engine"),
        ("backend.audio.model_manager", "backend.audio.model_manager", "Model manager"),
        ("backend.agent", "backend.agent", "Agent components"),
        ("backend.ws_manager", "backend.ws_manager", "WebSocket manager"),
        ("backend.state_manager", "backend.state_manager", "State manager"),
    ]
    
    backend_ok = all(check_dependency(*dep) for dep in backend_deps)
    print()
    
    # Test voice command import
    print("Voice Command Handler:")
    print("-" * 70)
    try:
        from backend.audio.voice_command import VoiceCommandHandler, VoiceState
        print(f"✅ VoiceCommandHandler      - Class imported successfully")
        print(f"✅ VoiceState               - Enum imported successfully")
        voice_ok = True
    except Exception as e:
        print(f"❌ VoiceCommandHandler      - FAILED to import")
        print(f"   Error: {e}")
        voice_ok = False
    print()
    
    # Test main.py import
    print("Main Module:")
    print("-" * 70)
    try:
        from backend.main import voice_handler
        print(f"✅ voice_handler            - Module-level variable accessible")
        print(f"   Current value: {voice_handler}")
        main_ok = True
    except Exception as e:
        print(f"❌ voice_handler            - FAILED to import")
        print(f"   Error: {e}")
        main_ok = False
    print()
    
    # Summary
    print("=" * 70)
    print("Summary:")
    print("=" * 70)
    
    all_ok = core_ok and audio_ok and backend_ok and voice_ok and main_ok
    
    if all_ok:
        print("[SUCCESS] ALL DEPENDENCIES INSTALLED")
        print()
        print("Phase 1 is ready for testing!")
        print()
        print("Next steps:")
        print("1. Run: python test_audio_pipeline.py")
        print("2. Run: python test_wake_word.py")
        print("3. Run: python backend/main.py")
        print("4. Start frontend: npm run dev")
        print()
        print("See md/TESTING-PHASE1.md for detailed testing instructions")
        return 0
    else:
        print("[ERROR] SOME DEPENDENCIES ARE MISSING")
        print()
        print("To install missing dependencies:")
        print("  pip install -r requirements.txt")
        print()
        print("If specific packages fail, try installing them individually:")
        print("  pip install <package-name>")
        return 1

if __name__ == "__main__":
    sys.exit(main())
